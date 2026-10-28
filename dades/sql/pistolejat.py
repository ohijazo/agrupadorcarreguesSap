"""Dades del pistolejat per SQL Server directe. Contracte a `dades/pistolejat.py`."""
from __future__ import annotations

from dades.sql.carregues import connectar

# SQL Server admet fins a 2100 parametres per consulta; anem molt per sota.
_TROS = 500


def _trossos(valors: list[int]):
    for n in range(0, len(valors), _TROS):
        yield valors[n:n + _TROS]


def obtenir_dades_pistolejat(carregues: list[int]) -> dict:
    """Linies obertes de les comandes obertes d'aquestes carregues, les
    lectures de `@SEIOPIC` encara sense albara, i l'ultim estat de cada comanda.

    `carregues` son DocEntry de `@SEI_ORDENCARGA`.
    """
    ids = sorted({int(c) for c in carregues or []})
    if not ids:
        return {"comandes": [], "pistolejats": [], "estats": {}}

    comandes: dict[int, dict] = {}
    pistolejats: list[dict] = []
    estats: dict[int, str] = {}

    conn = connectar()
    try:
        for tros in _trossos(ids):
            ph = ",".join(["?"] * len(tros))
            rows = conn.execute(f"""
                SELECT o.DocEntry, o.DocNum, o.U_SEIOrdCargId AS carrega,
                       RTRIM(o.CardCode) AS cli_codi, RTRIM(o.CardName) AS cli_nom,
                       l.LineNum, RTRIM(l.ItemCode) AS art_codi,
                       RTRIM(l.Dscription) AS art_descrip, RTRIM(l.unitMsr) AS unitat,
                       l.PackQty, l.InvQty, l.OpenInvQty
                FROM   ORDR o WITH (NOLOCK)
                JOIN   RDR1 l WITH (NOLOCK) ON l.DocEntry = o.DocEntry
                WHERE  o.U_SEIOrdCargId IN ({ph})
                  AND  o.DocStatus = 'O' AND o.CANCELED = 'N'
                  AND  l.LineStatus = 'O'
                ORDER  BY o.DocEntry, l.LineNum
            """, *tros).fetchall()
            for r in rows:
                c = comandes.setdefault(r.DocEntry, {
                    "docentry": int(r.DocEntry),
                    "docnum": r.DocNum,
                    "carrega": int(r.carrega),
                    "cli_codi": r.cli_codi or "",
                    "cli_nom": (r.cli_nom or "").strip(),
                    "linies": [],
                })
                c["linies"].append({
                    "linia": int(r.LineNum),
                    "art_codi": r.art_codi or "",
                    "art_descrip": (r.art_descrip or "").strip(),
                    "unitat": r.unitat or "",
                    "sacs": float(r.PackQty or 0),
                    "kg": float(r.InvQty or 0),
                    "kg_oberts": float(r.OpenInvQty or 0),
                })

        docs = sorted(comandes)
        for tros in _trossos(docs):
            ph = ",".join(["?"] * len(tros))
            for r in conn.execute(f"""
                SELECT p.U_BaseEntry AS comanda, p.U_BaseLine AS linia,
                       SUM(p.U_Quantity) AS sacs, SUM(p.U_InvQty) AS kg
                FROM   [@SEIOPIC] p WITH (NOLOCK)
                WHERE  p.U_BaseObject = 17
                  AND  p.U_TargetEntry IS NULL
                  AND  p.U_BaseEntry IN ({ph})
                GROUP  BY p.U_BaseEntry, p.U_BaseLine
            """, *tros).fetchall():
                pistolejats.append({
                    "comanda": int(r.comanda),
                    "linia": int(r.linia),
                    "sacs": round(float(r.sacs or 0), 6),
                    "kg": round(float(r.kg or 0), 6),
                })

            # Ultim estat = la fila amb el Code mes alt (autoincremental).
            for r in conn.execute(f"""
                SELECT e.U_SEIDocEntry AS comanda, RTRIM(e.U_SEIEstado) AS estat
                FROM   [@SEIESTATSCOM] e WITH (NOLOCK)
                WHERE  e.Code = (SELECT MAX(e2.Code) FROM [@SEIESTATSCOM] e2 WITH (NOLOCK)
                                 WHERE e2.U_SEIDocEntry = e.U_SEIDocEntry)
                  AND  e.U_SEIDocEntry IN ({ph})
            """, *tros).fetchall():
                estats[int(r.comanda)] = r.estat or ""
    finally:
        conn.close()

    return {
        "comandes": [comandes[d] for d in docs],
        "pistolejats": sorted(pistolejats, key=lambda p: (p["comanda"], p["linia"])),
        "estats": estats,
    }
