"""Dades per a l'etiqueta de palet, per SQL Server directe.

Contracte (el mateix a `dades/sl/etiquetes.py`): `obtenir_adreces_comandes`
rep una llista de DocNum de comandes (ORDR) i torna
    {"Series/DocNum": {cli_codi, cli_nom, carrer, poblacio, cp}}
amb l'adreça d'enviament de la comanda (RDR12). La població es proposa com a
"destí" de l'etiqueta i a la pantalla es pot corregir.
"""
from __future__ import annotations

from dades.sql.carregues import connectar

_TROS = 500


def obtenir_adreces_comandes(docnums: list[int]) -> dict[str, dict]:
    nums = sorted({int(n) for n in docnums or []})
    if not nums:
        return {}
    out: dict[str, dict] = {}
    conn = connectar()
    try:
        for n in range(0, len(nums), _TROS):
            tros = nums[n:n + _TROS]
            ph = ",".join(["?"] * len(tros))
            for r in conn.execute(f"""
                SELECT o.Series, o.DocNum, RTRIM(o.CardCode) AS cli_codi, o.CardName,
                       a.StreetS, a.CityS, a.ZipCodeS
                FROM   ORDR o WITH (NOLOCK)
                LEFT   JOIN RDR12 a WITH (NOLOCK) ON a.DocEntry = o.DocEntry
                WHERE  o.DocNum IN ({ph})
            """, *tros).fetchall():
                out[f"{r.Series}/{r.DocNum}"] = {
                    "cli_codi": r.cli_codi or "",
                    "cli_nom": (r.CardName or "").strip(),
                    "carrer": (r.StreetS or "").strip(),
                    "poblacio": (r.CityS or "").strip(),
                    "cp": (r.ZipCodeS or "").strip(),
                }
    finally:
        conn.close()
    return out
