"""Albarans de venda de les carregues pel Service Layer. Contracte a
`dades/sql/albarans.py`; ha de retornar exactament el mateix
(`scripts/paritat_backends.py --funcio llistar_albarans_carregues`).

`CancelStatus` es l'equivalent de `ODLN.CANCELED`: csYes = 'Y',
csNo = 'N', csCancellation = 'C' (el document de cancel·lacio).
"""
from __future__ import annotations

from sl_lectura import odata as od
from sl_lectura.client import client

ALBARANS = "DeliveryNotes"


def llistar_albarans_carregues(carregues: list[int]) -> list[dict]:
    ids = sorted({int(c) for c in carregues or []})
    if not ids:
        return []
    c = client()
    albarans: list[dict] = []
    for tros in od.trossos(ids):
        for d in c.tot(
            ALBARANS,
            select="DocEntry,DocNum,DocDate,CardCode,CardName,U_SEIOrdCargId,"
                   "UserSign,DocumentStatus,CancelStatus",
            filtre=od.i(od.qualsevol_num("U_SEIOrdCargId", tros),
                        "CancelStatus ne 'csCancellation'"),
        ):
            albarans.append({
                "docentry": int(d["DocEntry"]),
                "docnum": int(d["DocNum"]),
                "data": (d.get("DocDate") or "")[:10] or None,
                "carrega": int(d["U_SEIOrdCargId"]),
                "cli_codi": (d.get("CardCode") or "").strip(),
                "cli_nom": (d.get("CardName") or "").strip(),
                "usuari": int(d["UserSign"]) if d.get("UserSign") is not None else None,
                "obert": d.get("DocumentStatus") == "bost_Open",
                "cancelat": d.get("CancelStatus") == "csYes",
            })
    return sorted(albarans, key=lambda a: (a["carrega"], a["docentry"]))
