"""Albarans de venda (ODLN) de les carregues, per SQL Server directe.

Contracte (el mateix a `dades/sl/albarans.py`): llista ordenada per carrega i
DocEntry, amb un dict per albara:

    docentry, docnum, data (YYYY-MM-DD), carrega, cli_codi, cli_nom,
    usuari (UserSign: 22/23 = SGA1/SGA2), obert, cancelat

No hi surten els documents de cancel·lacio (CANCELED = 'C'): son el contrapunt
intern de SAP d'un albara cancel·lat, no un albara que s'hagi d'imprimir.

`llistar_albarans_dates` torna el mateix dict, pero ordenat per data i
DocEntry descendents (els mes nous primer).

`llistar_albarans_granel_dates` i `albarans_granel_propi` son per al rol
'granel' i nomes existeixen per SQL: amb `SAP_BACKEND=sl` el commutador avisa
al log i fa servir SQL igualment.
"""
from __future__ import annotations

from datetime import date

from dades.sql.carregues import connectar

_TROS = 500


def llistar_albarans_carregues(carregues: list[int]) -> list[dict]:
    ids = sorted({int(c) for c in carregues or []})
    if not ids:
        return []
    albarans: list[dict] = []
    conn = connectar()
    try:
        for n in range(0, len(ids), _TROS):
            tros = ids[n:n + _TROS]
            ph = ",".join(["?"] * len(tros))
            for r in conn.execute(f"""
                SELECT o.DocEntry, o.DocNum, o.DocDate, o.U_SEIOrdCargId AS carrega,
                       RTRIM(o.CardCode) AS cli_codi, RTRIM(o.CardName) AS cli_nom,
                       o.UserSign, o.DocStatus, o.CANCELED
                FROM   ODLN o WITH (NOLOCK)
                WHERE  o.U_SEIOrdCargId IN ({ph})
                  AND  o.CANCELED <> 'C'
            """, *tros).fetchall():
                albarans.append(_fila(r))
    finally:
        conn.close()
    return sorted(albarans, key=lambda a: (a["carrega"], a["docentry"]))


def llistar_albarans_dates(desde: date, fins: date, usuaris: list[int]) -> list[dict]:
    """Albarans amb carrega fets pels `usuaris` de SAP (els de l'SGA) amb
    DocDate o CreateDate entre `desde` i `fins`, tots dos inclosos. L'SGA en
    fa amb la data de l'endema (SGA2): sense CreateDate no sortirien a "Avui"."""
    usuaris = sorted({int(u) for u in usuaris or []})
    if not usuaris:
        return []
    ph = ",".join(["?"] * len(usuaris))
    conn = connectar()
    try:
        files = conn.execute(f"""
            SELECT o.DocEntry, o.DocNum, o.DocDate, o.U_SEIOrdCargId AS carrega,
                   RTRIM(o.CardCode) AS cli_codi, RTRIM(o.CardName) AS cli_nom,
                   o.UserSign, o.DocStatus, o.CANCELED
            FROM   ODLN o WITH (NOLOCK)
            WHERE  ((o.DocDate >= ? AND o.DocDate <= ?)
                    OR (o.CreateDate >= ? AND o.CreateDate <= ?))
              AND  o.UserSign IN ({ph})
              AND  o.U_SEIOrdCargId IS NOT NULL
              AND  o.CANCELED <> 'C'
        """, desde, fins, desde, fins, *usuaris).fetchall()
        albarans = [_fila(r) for r in files]
    finally:
        conn.close()
    return sorted(albarans, key=lambda a: (a["data"] or "", a["docentry"]), reverse=True)


# --- Albarans de granel amb transport propi (rol 'granel') ------------------
# El mateix criteri que la pestanya "Albarans Granel (propi)" del tauler de
# Comandes pendents (P:\dashboard_ComandesPendents\02_sql\40_AlbaransGranelPropi.sql):
#   - almenys una linia d'un article "Es Granel" (propietat 5, QryGroup5);
#   - transportista efectiu d'Agri Energia: el de l'albara (U_SEITranportEf)
#     o, si es buit, el de la seva ordre de carrega ([@SEI_ORDENCARGA].U_SEITransp).
# No es filtra per usuari: els pot haver creat qualsevol usuari de SAP.
TRANSPORT_PROPI = ("006", "013", "014")   # Agri Energia: Volvo, Renault, Cisterna

_SQL_GRANEL_PROPI = f"""
    EXISTS (SELECT 1 FROM DLN1 l WITH (NOLOCK)
            JOIN   OITM i WITH (NOLOCK) ON i.ItemCode = l.ItemCode
            WHERE  l.DocEntry = o.DocEntry AND i.QryGroup5 = 'Y')
    AND COALESCE(NULLIF(o.U_SEITranportEf, ''), oc.U_SEITransp)
        IN ({",".join(f"'{c}'" for c in TRANSPORT_PROPI)})
"""


def llistar_albarans_granel_dates(desde: date, fins: date) -> list[dict]:
    """Albarans de granel amb transport propi, fets per qualsevol usuari, amb
    DocDate o CreateDate entre `desde` i `fins`. Mateix dict que
    `llistar_albarans_dates`; `carrega` pot ser None (sense ordre de carrega)."""
    conn = connectar()
    try:
        files = conn.execute(f"""
            SELECT o.DocEntry, o.DocNum, o.DocDate, o.U_SEIOrdCargId AS carrega,
                   RTRIM(o.CardCode) AS cli_codi, RTRIM(o.CardName) AS cli_nom,
                   o.UserSign, o.DocStatus, o.CANCELED
            FROM   ODLN o WITH (NOLOCK)
            LEFT JOIN [@SEI_ORDENCARGA] oc WITH (NOLOCK) ON oc.DocEntry = o.U_SEIOrdCargId
            WHERE  ((o.DocDate >= ? AND o.DocDate <= ?)
                    OR (o.CreateDate >= ? AND o.CreateDate <= ?))
              AND  o.CANCELED <> 'C'
              AND  {_SQL_GRANEL_PROPI}
        """, desde, fins, desde, fins).fetchall()
        albarans = [_fila(r) for r in files]
    finally:
        conn.close()
    return sorted(albarans, key=lambda a: (a["data"] or "", a["docentry"]), reverse=True)


def albarans_granel_propi(docentries: list[int]) -> set[int]:
    """Quins d'aquests DocEntry son albarans de granel amb transport propi. El
    rol 'granel' nomes pot imprimir aquests."""
    ids = sorted({int(d) for d in docentries or []})
    if not ids:
        return set()
    trobats: set[int] = set()
    conn = connectar()
    try:
        for n in range(0, len(ids), _TROS):
            tros = ids[n:n + _TROS]
            ph = ",".join(["?"] * len(tros))
            for r in conn.execute(f"""
                SELECT o.DocEntry
                FROM   ODLN o WITH (NOLOCK)
                LEFT JOIN [@SEI_ORDENCARGA] oc WITH (NOLOCK) ON oc.DocEntry = o.U_SEIOrdCargId
                WHERE  o.DocEntry IN ({ph})
                  AND  {_SQL_GRANEL_PROPI}
            """, *tros).fetchall():
                trobats.add(int(r.DocEntry))
    finally:
        conn.close()
    return trobats


def _fila(r) -> dict:
    return {
        "docentry": int(r.DocEntry),
        "docnum": int(r.DocNum),
        "data": r.DocDate.strftime("%Y-%m-%d") if r.DocDate else None,
        "carrega": int(r.carrega) if r.carrega is not None else None,
        "cli_codi": r.cli_codi or "",
        "cli_nom": (r.cli_nom or "").strip(),
        "usuari": int(r.UserSign) if r.UserSign is not None else None,
        "obert": r.DocStatus == "O",
        "cancelat": r.CANCELED == "Y",
    }
