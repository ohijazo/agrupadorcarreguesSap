"""Albarans de venda (ODLN) de les carregues, per SQL Server directe.

Contracte (el mateix a `dades/sl/albarans.py`): llista ordenada per carrega i
DocEntry, amb un dict per albara:

    docentry, docnum, data (YYYY-MM-DD), carrega, cli_codi, cli_nom,
    usuari (UserSign: 22/23 = SGA1/SGA2), obert, cancelat

No hi surten els documents de cancel·lacio (CANCELED = 'C'): son el contrapunt
intern de SAP d'un albara cancel·lat, no un albara que s'hagi d'imprimir.
"""
from __future__ import annotations

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
                albarans.append({
                    "docentry": int(r.DocEntry),
                    "docnum": int(r.DocNum),
                    "data": r.DocDate.strftime("%Y-%m-%d") if r.DocDate else None,
                    "carrega": int(r.carrega),
                    "cli_codi": r.cli_codi or "",
                    "cli_nom": (r.cli_nom or "").strip(),
                    "usuari": int(r.UserSign) if r.UserSign is not None else None,
                    "obert": r.DocStatus == "O",
                    "cancelat": r.CANCELED == "Y",
                })
    finally:
        conn.close()
    return sorted(albarans, key=lambda a: (a["carrega"], a["docentry"]))
