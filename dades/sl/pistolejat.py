"""Dades del pistolejat pel Service Layer. Contracte a `dades/pistolejat.py`.

Ha de retornar exactament el mateix que `dades/sql/pistolejat.py`
(`scripts/paritat_backends.py --funcio obtenir_dades_pistolejat`).

Les dues UDT de l'addon no tenen objecte, i per aixo van AMB prefix `U_`.
El Service Layer no pot filtrar ni agregar sobre linies de document: les
linies venen inline amb `DocumentLines` al `$select` i el filtre de linia
oberta i les sumes es fan en Python.
"""
from __future__ import annotations

from sl_lectura import odata as od
from sl_lectura.client import client

COMANDES = "Orders"
PISTOLEJATS = "U_SEIOPIC"
ESTATS = "U_SEIESTATSCOM"


def obtenir_dades_pistolejat(carregues: list[int]) -> dict:
    """Vegeu la versio SQL. Una crida per tros de 40 carregues a `Orders`, i
    una per tros de 40 comandes a cadascuna de les dues UDT."""
    ids = sorted({int(c) for c in carregues or []})
    if not ids:
        return {"comandes": [], "pistolejats": [], "estats": {}}

    c = client()
    comandes: dict[int, dict] = {}
    for tros in od.trossos(ids):
        for o in c.tot(
            COMANDES,
            select="DocEntry,DocNum,CardCode,CardName,U_SEIOrdCargId,DocumentLines",
            filtre=od.i(od.qualsevol_num("U_SEIOrdCargId", tros),
                        "DocumentStatus eq 'bost_Open'",
                        "Cancelled eq 'tNO'"),
        ):
            linies = [
                {
                    "linia": int(l.get("LineNum") or 0),
                    "art_codi": (l.get("ItemCode") or "").strip(),
                    "art_descrip": (l.get("ItemDescription") or "").strip(),
                    "unitat": (l.get("MeasureUnit") or "").strip(),
                    "sacs": float(l.get("PackageQuantity") or 0),
                    "kg": float(l.get("InventoryQuantity") or 0),
                    "kg_oberts": float(l.get("RemainingOpenInventoryQuantity") or 0),
                }
                for l in sorted(o.get("DocumentLines") or [], key=lambda x: x.get("LineNum") or 0)
                if l.get("LineStatus") == "bost_Open"
            ]
            if not linies:   # el JOIN del SQL tampoc no torna comandes sense linies obertes
                continue
            comandes[int(o["DocEntry"])] = {
                "docentry": int(o["DocEntry"]),
                "docnum": o.get("DocNum"),
                "carrega": int(o["U_SEIOrdCargId"]),
                "cli_codi": (o.get("CardCode") or "").strip(),
                "cli_nom": (o.get("CardName") or "").strip(),
                "linies": linies,
            }

    docs = sorted(comandes)
    sumes: dict[tuple[int, int], dict] = {}
    estats: dict[int, str] = {}
    ultim_code: dict[int, int] = {}
    for tros in od.trossos(docs):
        for p in c.tot(
            PISTOLEJATS,
            select="U_BaseEntry,U_BaseLine,U_Quantity,U_InvQty",
            filtre=od.i("U_BaseObject eq 17", "U_TargetEntry eq null",
                        od.qualsevol_num("U_BaseEntry", tros)),
        ):
            acc = sumes.setdefault((int(p["U_BaseEntry"]), int(p["U_BaseLine"])),
                                   {"sacs": 0.0, "kg": 0.0})
            acc["sacs"] += float(p.get("U_Quantity") or 0)
            acc["kg"] += float(p.get("U_InvQty") or 0)

        # Ultim estat = Code mes alt. Son poques files per comanda (~5).
        for e in c.tot(
            ESTATS,
            select="Code,U_SEIDocEntry,U_SEIEstado",
            filtre=od.qualsevol_num("U_SEIDocEntry", tros),
        ):
            doc, code = int(e["U_SEIDocEntry"]), int(e["Code"])
            if code > ultim_code.get(doc, -1):
                ultim_code[doc] = code
                estats[doc] = (e.get("U_SEIEstado") or "").strip()

    pistolejats = [
        {"comanda": com, "linia": lin, "sacs": round(v["sacs"], 6), "kg": round(v["kg"], 6)}
        for (com, lin), v in sorted(sumes.items())
    ]
    return {
        "comandes": [comandes[d] for d in docs],
        "pistolejats": pistolejats,
        "estats": estats,
    }
