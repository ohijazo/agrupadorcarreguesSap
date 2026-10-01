"""Refresca els agregats per carrega llegint les comandes del Service Layer.

Us:
    python scripts/refrescar_agregats.py            # incremental (per cron)
    python scripts/refrescar_agregats.py --complet  # reconstruccio sencera

Al servidor va amb un timer de systemd cada 2 minuts per a l'incremental i un
cop de matinada per al complet. Es un proces curt, de manera que aqui SI es
correcte obrir i tancar sessio a cada execucio (la regla de no fer login per
peticio es per al servidor web, no per als processos de CLI).

Per que existeix: vegeu db/migrations/006_agregats_carrega.sql. El resum es
que el Service Layer no pot agregar ni filtrar sobre linies de document, i
portar-se les linies a cada peticio no es viable (247 camps per linia, ~19 KB
per comanda, i el llistat demana 500-1000 carregues).
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

# `import app` primer: carrega el .env i posa PREPARACIO_PATH al sys.path.
# Sense aixo, importar db o dades directament falla amb "PG_HOST no configurat".
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import app  # noqa: F401,E402

from dades import agregats  # noqa: E402
from dades.sl import cache_articles  # noqa: E402
from dades.sl import odata as q  # noqa: E402
from dades.sl.client import client  # noqa: E402

log = logging.getLogger("agrupacio")

COMANDES = "Orders"
CAMPS = "DocEntry,U_SEIOrdCargId,DocumentLines"


def _agregat(comanda: dict, unitats_art: dict[str, str]) -> dict:
    """Calcula els 4 camps d'una comanda, amb la semantica EXACTA del SQL.

    Hi ha una asimetria deliberada que cal respectar: el `kg_total` del SQL no
    fa cap JOIN amb OITM, aixi que compta totes les linies; en canvi
    `palletitzable` i `is_granel` surten de subconsultes amb JOIN **INNER** a
    OITM, i per tant una linia amb un article que no es al mestre no hi compta.
    No es un descuit meu: es com funciona avui i el llistat ha de donar el
    mateix.
    """
    kg = 0.0
    te_pall = False
    te_granel = False
    arts: set[str] = set()

    for l in comanda.get("DocumentLines") or []:
        art = (l.get("ItemCode") or "").strip()
        quan = float(l.get("Quantity") or 0)
        pack = float(l.get("PackageQuantity") or 0)
        unitats = pack if pack else quan   # COALESCE(NULLIF(PackQty,0), Quantity)

        kg += quan                         # sense JOIN amb OITM: totes hi compten
        if art:
            arts.add(art)
        if art not in unitats_art:         # equivalent al JOIN INNER amb OITM
            continue
        tun = (unitats_art.get(art) or "").strip().upper()
        if unitats > 0 and tun not in ("UNI", "GRA"):
            te_pall = True
        if tun == "GRA" and quan > 0:
            te_granel = True

    return {
        "order_docentry": int(comanda["DocEntry"]),
        "carrega_docentry": int(comanda.get("U_SEIOrdCargId") or 0),
        "kg": round(kg, 4),
        "te_palletitzable": te_pall,
        "te_granel": te_granel,
        "item_codes": sorted(arts),
    }


def _unitats_de(comandes: list[dict]) -> dict[str, str]:
    codis = {(l.get("ItemCode") or "").strip()
             for c in comandes for l in (c.get("DocumentLines") or [])
             if (l.get("ItemCode") or "").strip()}
    return cache_articles.unitats_venda(sorted(codis)) if codis else {}


def refresc_complet() -> int:
    """Reconstrueix la taula sencera a partir de totes les comandes assignades."""
    c = client()
    # Assignada = U_SEIOrdCargId > 0. A SAP les no assignades son nul·les o 0,
    # i cap DocEntry de carrega no val 0, aixi que el `gt 0` les descarta totes.
    comandes = c.tot(COMANDES, select=CAMPS, filtre="U_SEIOrdCargId gt 0", ordre="DocEntry")
    unitats = _unitats_de(comandes)
    files = [_agregat(x, unitats) for x in comandes]
    files = [f for f in files if f["carrega_docentry"] > 0]
    n = agregats.substitueix_tot(files)
    agregats.marca_refresc(complet=True, comandes=n)
    log.info("refresc complet: %d comandes", n)
    return n


def refresc_incremental(dies: int = 2) -> int:
    """Refresca les comandes modificades els ultims `dies` dies.

    `UpdateDate` a SAP no porta hora, aixi que el gra minim es el dia. Agafem
    dos dies per defecte perque una execucio que falli no deixi un forat.
    """
    c = client()
    desde = (datetime.now() - timedelta(days=dies)).date()
    comandes = c.tot(COMANDES, select=CAMPS,
                     filtre=f"UpdateDate ge {q.data_hora(desde)}", ordre="DocEntry")
    unitats = _unitats_de(comandes)

    a_desar = []
    a_esborrar = []
    for x in comandes:
        f = _agregat(x, unitats)
        if f["carrega_docentry"] > 0:
            a_desar.append(f)
        else:
            # La comanda s'ha desassignat de la carrega: la seva fila ha de
            # desapareixer. Una reassignacio NO necessita cap tracte especial,
            # perque desem una fila per comanda i l'agregat per carrega es
            # calcula amb un GROUP BY en llegir.
            a_esborrar.append(f["order_docentry"])

    n = agregats.desa_comandes(a_desar)
    m = agregats.esborra_comandes(a_esborrar)
    agregats.marca_refresc(complet=False, comandes=n)
    log.info("refresc incremental des de %s: %d desades, %d esborrades", desde, n, m)
    return n


def main() -> int:
    p = argparse.ArgumentParser(description="Refresca els agregats per carrega.")
    p.add_argument("--complet", action="store_true",
                   help="Reconstruccio sencera en lloc d'incremental.")
    p.add_argument("--dies", type=int, default=2,
                   help="Finestra de l'incremental en dies (per defecte 2).")
    args = p.parse_args()

    try:
        if args.complet:
            n = refresc_complet()
        else:
            n = refresc_incremental(args.dies)
    except Exception as e:
        # L'error queda desat a agregats_meta perque /health el pugui ensenyar:
        # un refrescador encallat en silenci es la pitjor fallada d'aquest
        # disseny, perque el llistat segueix responent amb dades velles.
        log.exception("refresc d'agregats fallit")
        try:
            agregats.marca_refresc(complet=args.complet, comandes=0, error=str(e)[:500])
        except Exception:
            log.exception("i tampoc he pogut desar l'error a agregats_meta")
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    estat = agregats.estat()
    print(f"OK - {n} comandes | antiguitat {estat.get('antiguitat_s')} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
