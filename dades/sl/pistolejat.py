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


def obtenir_dades_pistolejat(carregues: list[int], incloure_tancades: bool = False) -> dict:
    """Vegeu la versio SQL. Una crida per tros de 40 carregues a `Orders`, i
    una per tros de 40 comandes a cadascuna de les dues UDT."""
    ids = sorted({int(c) for c in carregues or []})
    if not ids:
        return {"comandes": [], "pistolejats": [], "pistolejats_cancelats": [], "estats": {}}

    c = client()
    comandes: dict[int, dict] = {}
    for tros in od.trossos(ids):
        for o in c.tot(
            COMANDES,
            select="DocEntry,DocNum,CardCode,CardName,U_SEIOrdCargId,DocumentLines",
            filtre=od.i(od.qualsevol_num("U_SEIOrdCargId", tros),
                        "" if incloure_tancades else "DocumentStatus eq 'bost_Open'",
                        "Cancelled eq 'tNO'"),
        ):
            linies = [
                {
                    "linia": int(l.get("LineNum") or 0),
                    "art_codi": (l.get("ItemCode") or "").strip(),
                    "art_descrip": (l.get("ItemDescription") or "").strip(),
                    "unitat": (l.get("MeasureUnit") or "").strip(),
                    "granel": False,   # es completa a sota amb la propietat 5
                    "sacs": float(l.get("PackageQuantity") or 0),
                    "kg": float(l.get("InventoryQuantity") or 0),
                    # Una linia tancada a ma (sense albara) conserva la
                    # quantitat oberta: no queda res per preparar.
                    "kg_oberts": float(l.get("RemainingOpenInventoryQuantity") or 0)
                                 if l.get("LineStatus") == "bost_Open" else 0.0,
                }
                for l in sorted(o.get("DocumentLines") or [], key=lambda x: x.get("LineNum") or 0)
                if incloure_tancades or l.get("LineStatus") == "bost_Open"
            ]
            if not linies:   # el JOIN del SQL tampoc no torna comandes sense linies
                continue
            comandes[int(o["DocEntry"])] = {
                "docentry": int(o["DocEntry"]),
                "docnum": o.get("DocNum"),
                "carrega": int(o["U_SEIOrdCargId"]),
                "cli_codi": (o.get("CardCode") or "").strip(),
                "cli_nom": (o.get("CardName") or "").strip(),
                "linies": linies,
            }

    # Granel: propietat 5 de l'article ("Es Granel", Properties5) o unitat
    # GRA. Les linies de comanda no porten les propietats de l'article.
    codis = sorted({l["art_codi"] for cm in comandes.values() for l in cm["linies"] if l["art_codi"]})
    granel: set[str] = set()
    for tros in od.trossos(codis):
        for it in c.tot("Items", select="ItemCode,Properties5", filtre=od.qualsevol_de("ItemCode", tros)):
            if it.get("Properties5") == "tYES":
                granel.add((it.get("ItemCode") or "").strip())
    for cm in comandes.values():
        for l in cm["linies"]:
            l["granel"] = l["art_codi"] in granel or l["unitat"] == "GRA"

    docs = sorted(comandes)
    sumes: dict[tuple[int, int], dict] = {}
    amb_albara: dict[tuple[int, int, int], dict] = {}
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

        # Lectures ja lligades a un albara: despres es mira quins albarans
        # estan cancel·lats (el Service Layer no pot fer el JOIN amb ODLN).
        for p in c.tot(
            PISTOLEJATS,
            select="U_BaseEntry,U_BaseLine,U_TargetEntry,U_Quantity,U_InvQty",
            filtre=od.i("U_BaseObject eq 17", "U_TargetType eq 15", "U_TargetEntry ne null",
                        od.qualsevol_num("U_BaseEntry", tros)),
        ):
            acc = amb_albara.setdefault(
                (int(p["U_BaseEntry"]), int(p["U_BaseLine"]), int(p["U_TargetEntry"])),
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

    # Dels albarans que tenen lectures, nomes els cancel·lats (CANCELED = 'Y').
    cancelats_docnum: dict[int, int] = {}
    for tros in od.trossos(sorted({alb for (_, _, alb) in amb_albara})):
        for d in c.tot(
            "DeliveryNotes",
            select="DocEntry,DocNum",
            filtre=od.i(od.qualsevol_num("DocEntry", tros), "CancelStatus eq 'csYes'"),
        ):
            cancelats_docnum[int(d["DocEntry"])] = int(d["DocNum"])
    pistolejats_cancelats = [
        {"comanda": com, "linia": lin, "albara": alb, "docnum": cancelats_docnum[alb],
         "sacs": round(v["sacs"], 6), "kg": round(v["kg"], 6)}
        for (com, lin, alb), v in sorted(amb_albara.items())
        if alb in cancelats_docnum
    ]
    return {
        "comandes": [comandes[d] for d in docs],
        "pistolejats": pistolejats,
        "pistolejats_cancelats": pistolejats_cancelats,
        "estats": estats,
    }
