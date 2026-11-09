"""Dades per a l'etiqueta de palet pel Service Layer. Contracte a
`dades/sql/etiquetes.py`; ha de retornar exactament el mateix
(`scripts/paritat_backends.py --funcio obtenir_adreces_comandes`).

L'adreça d'enviament ve a `AddressExtension` (ShipToStreet, ShipToCity...),
l'equivalent de RDR12.
"""
from __future__ import annotations

from sl_lectura import odata as od
from sl_lectura.client import client


def obtenir_adreces_comandes(docnums: list[int]) -> dict[str, dict]:
    nums = sorted({int(n) for n in docnums or []})
    if not nums:
        return {}
    out: dict[str, dict] = {}
    c = client()
    for tros in od.trossos(nums):
        for o in c.tot(
            "Orders",
            select="Series,DocNum,CardCode,CardName,AddressExtension",
            filtre=od.qualsevol_num("DocNum", tros),
        ):
            adr = o.get("AddressExtension") or {}
            out[f"{o['Series']}/{o['DocNum']}"] = {
                "cli_codi": (o.get("CardCode") or "").strip(),
                "cli_nom": (o.get("CardName") or "").strip(),
                "carrer": (adr.get("ShipToStreet") or "").strip(),
                "poblacio": (adr.get("ShipToCity") or "").strip(),
                "cp": (adr.get("ShipToZipCode") or "").strip(),
            }
    return out
