"""Compara el backend SQL amb el de Service Layer, funcio per funcio.

Us:
    python scripts/paritat_backends.py                 # tot
    python scripts/paritat_backends.py --funcio llistar_carregues
    python scripts/paritat_backends.py --detall        # ensenya les diferencies

Codi de sortida 0 si tot coincideix, 1 si hi ha cap diferencia: serveix de
porta abans de commutar una funcio a produccio.

No es un test de pytest a proposit: necessita la BD real de SAP i els agregats
refrescats, i no te sentit a la bateria de tests unitaris. Val mes dir-ho clar
que fingir una cobertura que no hi es.

IMPORTANT: executar-ho DES DEL SERVIDOR i contra la companyia que faci servir
produccio. El cami de xarxa importa (l'app es a ae01farwebsrv i el Service
Layer a 192.168.11.238) i els temps mesurats en una base de proves de 85
carregues no extrapolen.
"""
import argparse
import inspect
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import app  # noqa: F401,E402  — carrega .env i PREPARACIO_PATH

from dades.sl import carregues as sl  # noqa: E402
from dades.sql import carregues as sql  # noqa: E402

RANG_AMPLI = ("2020-01-01", "2030-12-31")


def _casos_llistar() -> list[dict]:
    """Matriu de casos del llistat.

    Cobreix el que mes facilment divergeix: la frontera de la finestra (el
    `fins + 1 dia` exclusiu), les files amb U_SEIDataS nul·la barrejades amb
    les que la tenen (l'ordre del COALESCE), la paginacio als limits, i els
    tres filtres per separat i combinats.
    """
    casos: list[dict] = []
    rangs = [
        ("2026-09-01", "2026-09-01"),   # un sol dia
        ("2026-09-01", "2026-09-07"),   # una setmana
        ("2026-08-01", "2026-08-31"),   # un mes
        ("2026-01-01", "2026-12-31"),   # un any
        ("2026-12-01", "2026-12-31"),   # finestra probablement buida
        RANG_AMPLI,
    ]
    for d, f in rangs:
        casos.append({"desde": d, "fins": f})
        casos.append({"desde": d, "fins": f, "limit": 5})
        casos.append({"desde": d, "fins": f, "limit": 5, "offset": 3})
        casos.append({"desde": d, "fins": f, "limit": 1})
    d, f = RANG_AMPLI
    for e in (1, 2, 3, 4):
        casos.append({"desde": d, "fins": f, "estat": e})
    try:
        tr = [t["tra_codi"] for t in sql.llistar_transportistes()[:3]]
    except Exception:
        tr = []
    if tr:
        casos.append({"desde": d, "fins": f, "tra_codis": tr[:1]})
        casos.append({"desde": d, "fins": f, "tra_codis": tr})
        casos.append({"desde": d, "fins": f, "tra_codis": tr[:1], "estat": 1})
    casos.append({"desde": d, "fins": f, "tra_codis": ["NOEXISTEIX"]})
    try:
        arts = [r["art_codi"] for r in sql.cercar_articles("33", 3)]
    except Exception:
        arts = []
    for a in arts:
        casos.append({"desde": d, "fins": f, "art_codi": a})
    casos.append({"desde": d, "fins": f, "art_codi": "NOEXISTEIX"})
    # offset mes enlla del total
    casos.append({"desde": d, "fins": f, "limit": 10, "offset": 99999})
    return casos


def _casos_per_carrega(fn_nom: str) -> list[dict]:
    """Un cas per cada carrega existent, per a les funcions de detall."""
    items = sql.llistar_carregues(*RANG_AMPLI, limit=1000)["items"]
    casos = [{"eje": c["eje_ejercicio"], "sca": c["sca_serie"], "car": c["car_numero"]}
             for c in items]
    # Casos limit: car buit, no numeric i inexistent.
    casos += [{"eje": "SAP", "sca": "-1", "car": v} for v in ("", "xyz", "999999")]
    return casos


def _casos_articles() -> list[dict]:
    """Textos que toquen majuscules, accents i les dues vies de coincidencia.

    La collation de la BD es CP850_CI_AS: insensible a majuscules pero
    SENSIBLE a accents, i es el que ha de reproduir el backend nou.
    """
    casos = []
    for q in ("33", "330", "HARINA", "harina", "Harina", "ESPELTA", "espelta",
              "MOLTA", "SAL", "SAC", "a", "xxxxxx", "00"):
        for lim in (20, 5, 50):
            casos.append({"q": q, "limit": lim})
    return casos


def _casos_descrip() -> list[dict]:
    """Descripcions d'articles: llistes buides, amb duplicats i amb codis que
    no existeixen (que han de desapareixer del resultat, no petar)."""
    codis = [r["art_codi"] for r in sql.cercar_articles("33", 10)]
    return [
        {"codis": []},
        {"codis": codis},
        {"codis": codis + ["NO_EXISTEIX"]},
        {"codis": (codis[:1] * 3) if codis else []},
        {"codis": ["NO_EXISTEIX"]},
    ]


FUNCIONS = {
    "llistar_carregues": _casos_llistar,
    "obtenir_descrip_articles": _casos_descrip,
    "llistar_estats_carregues": lambda: [{}],
    "llistar_transportistes": lambda: [{}],
    "cercar_articles": _casos_articles,
    "obtenir_comandes_carrega": lambda: _casos_per_carrega("obtenir_comandes_carrega"),
    "resum_carrega": lambda: _casos_per_carrega("resum_carrega"),
}


def _normalitza(valor) -> str:
    return json.dumps(valor, sort_keys=True, default=str, ensure_ascii=False)


def _primera_diferencia(a, b) -> str:
    """Descriu la primera diferencia d'una manera que es pugui llegir.

    Mira primer el total i l'ordre, que es el que normalment falla, i nomes
    despres baixa a camp per camp.
    """
    if isinstance(a, dict) and "items" in a and isinstance(b, dict):
        if a.get("total") != b.get("total"):
            return f"total: SQL {a.get('total')} | SL {b.get('total')}"
        ida = [x.get("carrega_id") for x in a["items"]]
        idb = [x.get("carrega_id") for x in b.get("items", [])]
        if ida != idb:
            return f"ordre o contingut:\n      SQL {ida[:6]}\n      SL  {idb[:6]}"
        for x, y in zip(a["items"], b["items"]):
            dif = [k for k in x if x[k] != y.get(k)]
            if dif:
                det = "; ".join(f"{k}: SQL {x[k]!r} | SL {y.get(k)!r}" for k in dif[:3])
                return f"carrega {x.get('carrega_id')} -> {det}"
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if _normalitza(a.get(k)) != _normalitza(b.get(k)):
                return f"clau {k}:\n      SQL {_normalitza(a.get(k))[:200]}\n      SL  {_normalitza(b.get(k))[:200]}"
    return f"SQL {_normalitza(a)[:200]}\n      SL  {_normalitza(b)[:200]}"


def compara(nom: str, detall: bool) -> tuple[int, int, float, float]:
    casos = FUNCIONS[nom]()
    fa, fb = getattr(sql, nom), getattr(sl, nom)
    ko = 0
    ta = tb = 0.0
    for kw in casos:
        t = time.time()
        a = fa(**kw)
        ta += time.time() - t
        t = time.time()
        b = fb(**kw)
        tb += time.time() - t
        if _normalitza(a) == _normalitza(b):
            continue
        ko += 1
        if detall and ko <= 5:
            print(f"    DIFEREIX {json.dumps(kw, ensure_ascii=False)}")
            print(f"      {_primera_diferencia(a, b)}")
    return len(casos), ko, ta, tb


def comprova_signatures(noms: list[str]) -> int:
    """Les dues implementacions han de tenir la MATEIXA signatura.

    Aixo no es zel: la facana passa *args i **kwargs tal com arriben, de manera
    que si un parametre es diu diferent, qualsevol cridant que el passi per nom
    peta nomes amb un dels dos backends. Em va passar amb `cercar_articles`,
    on la versio de Service Layer havia batejat el parametre `q_text`.
    """
    ko = 0
    for nom in noms:
        sa = inspect.signature(getattr(sql, nom))
        sb = inspect.signature(getattr(sl, nom))
        if str(sa) != str(sb):
            ko += 1
            print(f"  SIGNATURA DIFERENT a {nom}:")
            print(f"    SQL {sa}")
            print(f"    SL  {sb}")
    return ko


def main() -> int:
    p = argparse.ArgumentParser(description="Paritat entre els backends SQL i Service Layer.")
    p.add_argument("--funcio", choices=sorted(FUNCIONS), help="Nomes aquesta funcio.")
    p.add_argument("--detall", action="store_true", help="Ensenya les diferencies trobades.")
    args = p.parse_args()

    noms = [args.funcio] if args.funcio else sorted(FUNCIONS)

    ko_sig = comprova_signatures(noms)
    if ko_sig:
        print()
        print(f"{ko_sig} signatures no coincideixen. Arregla-ho abans de comparar.")
        return 1

    print(f"{'FUNCIO':<26} {'CASOS':>6} {'KO':>4} {'SQL':>10} {'SL':>10}")
    total_ko = 0
    for nom in noms:
        n, ko, ta, tb = compara(nom, args.detall)
        total_ko += ko
        marca = "" if ko == 0 else "  <-- revisar"
        print(f"{nom:<26} {n:>6} {ko:>4} {ta / max(n, 1) * 1000:>8.1f}ms "
              f"{tb / max(n, 1) * 1000:>8.1f}ms{marca}")

    print()
    if total_ko:
        print(f"HI HA {total_ko} DIFERENCIES. No commutis cap funcio amb diferencies.")
        return 1
    print("Paritat completa: els dos backends donen el mateix a tots els casos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
