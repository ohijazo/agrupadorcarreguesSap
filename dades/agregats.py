"""Lectura i escriptura dels agregats per carrega a PostgreSQL.

Vegeu `db/migrations/006_agregats_carrega.sql` per al motiu d'existir d'aquesta
taula. En resum: els quatre camps derivats del llistat (`kg_total`,
`num_comandes`, `palletitzable`, `is_granel`) no es poden calcular en viu pel
Service Layer, perque no permet agregar ni filtrar sobre linies de document i
les linies no es poden retallar amb `$select`.

Qui escriu aqui es `scripts/refrescar_agregats.py`. Qui llegeix es
`dades/sl/carregues.py`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import db

log = logging.getLogger("agrupacio")


# =============================================================================
# Lectura (la fa el llistat)
# =============================================================================
def per_carrega(carrega_docentries: list[int]) -> dict[int, dict]:
    """Agregats de les carregues demanades: `DocEntry -> {4 camps}`.

    Les carregues sense cap comanda no surten al resultat; el cridant hi ha de
    posar els valors neutres, igual que el `ISNULL(..., 0)` del SQL.
    """
    if not carrega_docentries:
        return {}
    files = db.fetch_all(
        """
        SELECT carrega_docentry,
               COALESCE(SUM(kg), 0)        AS kg_total,
               COUNT(*)                    AS num_comandes,
               bool_or(te_palletitzable)   AS palletitzable,
               bool_or(te_granel)          AS is_granel
        FROM   ordre_carrega_cache
        WHERE  carrega_docentry = ANY(%s)
        GROUP  BY carrega_docentry
        """,
        (list(carrega_docentries),),
    )
    return {
        int(f["carrega_docentry"]): {
            "kg_total": float(f["kg_total"] or 0),
            "num_comandes": int(f["num_comandes"] or 0),
            "palletitzable": bool(f["palletitzable"]),
            "is_granel": bool(f["is_granel"]),
        }
        for f in files
    }


def carregues_amb_article(art_codi: str) -> set[int]:
    """Carregues que tenen alguna comanda amb aquest article.

    Substitueix l'`EXISTS` correlacionat del SQL. Com que es resol abans de
    paginar, el filtre afecta tambe el comptador total, igual que ara.
    """
    files = db.fetch_all(
        "SELECT DISTINCT carrega_docentry FROM ordre_carrega_cache "
        "WHERE item_codes @> ARRAY[%s]::text[]",
        (art_codi,),
    )
    return {int(f["carrega_docentry"]) for f in files}


def estat() -> dict:
    """Estat del refrescador, per a /health."""
    f = db.fetch_one(
        "SELECT ultim_refresc_complet, ultim_refresc_incr, ultim_error, comandes "
        "FROM agregats_meta WHERE id = 1"
    )
    if not f:
        return {"ok": False, "msg": "agregats_meta sense fila"}
    # El MES RECENT dels dos, no l'incremental sempre. Amb `or` es reportava
    # l'antiguitat de l'incremental anterior just despres d'un refresc complet
    # (vist al servidor: "antiguitat 104 s" amb la taula acabada de
    # reconstruir), i el /health se n'hauria menjat el fals positiu.
    marques = [m for m in (f["ultim_refresc_incr"], f["ultim_refresc_complet"])
               if m is not None]
    antiguitat = None
    if marques:
        ara = datetime.now(timezone.utc)
        ultim = max(m.replace(tzinfo=timezone.utc) if m.tzinfo is None else m
                    for m in marques)
        antiguitat = (ara - ultim).total_seconds()
    # `comandes` ha de dir quantes n'hi ha a la cache, no quantes n'ha tocat
    # l'ultima execucio. Son coses diferents i la segona enganya: despres d'un
    # refresc complet de 88 comandes, el primer incremental (que nomes mira les
    # modificades els ultims dos dies) deixava el camp a 17, i al /health es
    # llegia com si la cache s'hagues buidat.
    fila = db.fetch_one("SELECT count(*) AS n FROM ordre_carrega_cache")
    return {
        "antiguitat_s": None if antiguitat is None else int(antiguitat),
        "comandes": int((fila or {}).get("n") or 0),
        "ultim_lot": int(f["comandes"] or 0),
        "error": f["ultim_error"] or "",
    }


# =============================================================================
# Escriptura (la fa el refrescador)
# =============================================================================
def desa_comandes(files: list[dict]) -> int:
    """Insereix o actualitza els agregats de les comandes donades.

    Cada element: {order_docentry, carrega_docentry, kg, te_palletitzable,
    te_granel, item_codes}.
    """
    if not files:
        return 0
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ordre_carrega_cache
                    (order_docentry, carrega_docentry, kg, te_palletitzable,
                     te_granel, item_codes, refrescat_at)
                VALUES (%(order_docentry)s, %(carrega_docentry)s, %(kg)s,
                        %(te_palletitzable)s, %(te_granel)s, %(item_codes)s, NOW())
                ON CONFLICT (order_docentry) DO UPDATE SET
                    carrega_docentry = EXCLUDED.carrega_docentry,
                    kg               = EXCLUDED.kg,
                    te_palletitzable = EXCLUDED.te_palletitzable,
                    te_granel        = EXCLUDED.te_granel,
                    item_codes       = EXCLUDED.item_codes,
                    refrescat_at     = NOW()
                """,
                files,
            )
    return len(files)


def esborra_comandes(order_docentries: list[int]) -> int:
    """Treu comandes que ja no han de ser-hi (desassignades de tota carrega)."""
    if not order_docentries:
        return 0
    return db.execute(
        "DELETE FROM ordre_carrega_cache WHERE order_docentry = ANY(%s)",
        (list(order_docentries),),
    )


def substitueix_tot(files: list[dict]) -> int:
    """Reconstruccio completa, dins d'una transaccio.

    S'esborra i es torna a omplir en el mateix commit perque el llistat no
    pugui veure mai la taula a mitges.
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ordre_carrega_cache")
            if files:
                cur.executemany(
                    """
                    INSERT INTO ordre_carrega_cache
                        (order_docentry, carrega_docentry, kg, te_palletitzable,
                         te_granel, item_codes, refrescat_at)
                    VALUES (%(order_docentry)s, %(carrega_docentry)s, %(kg)s,
                            %(te_palletitzable)s, %(te_granel)s, %(item_codes)s, NOW())
                    """,
                    files,
                )
    return len(files)


def marca_refresc(complet: bool, comandes: int, error: str = "") -> None:
    camp = "ultim_refresc_complet" if complet else "ultim_refresc_incr"
    db.execute(
        f"""
        UPDATE agregats_meta
        SET {camp} = NOW(), comandes = %s, ultim_error = %s
        WHERE id = 1
        """,
        (comandes, error),
    )
