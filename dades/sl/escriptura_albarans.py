"""Cancel·lacio d'albarans de venda a SAP. Es la PRIMERA escriptura de l'app.

Va sempre pel Service Layer, sigui quin sigui el backend de lectura: SAP no
admet escriure per SQL. `POST DeliveryNotes(N)/Cancel` fa el mateix que
"Cancel·lar" al client SAP: crea el document de cancel·lacio (CANCELED = 'C'),
marca l'original com a cancel·lat (CANCELED = 'Y') i torna a obrir les linies
de la comanda. El TransactionNotification de SEIDOR salta igual que des del
client (torna la comanda a CONFIRMADA a `@SEIESTATSCOM`). Les files de
`@SEIOPIC` de l'albara es queden com a historic apuntant-hi i l'SGA deixa
tornar a preparar la comanda: no s'han de tocar (confirmat per SEIDOR).

Les condicions de `motiu_no_cancelable` les comprova SAP de totes maneres; les
mirem abans per donar un missatge clar en lloc de l'error cru de SAP. Una
linia tancada vol dir que ja te factura o devolucio (`TargetType` surt buit
pel Service Layer, aixi que no el podem fer servir).
"""
from __future__ import annotations

import logging

import requests

from sap_service_layer import SLError, SLNotFoundError  # ve de PREPARACIO_PATH
from sl_lectura.client import client

log = logging.getLogger("agrupacio")

_SELECT = "DocEntry,DocNum,DocumentStatus,CancelStatus,UserSign,U_SEIOrdCargId,DocumentLines"


def estat_albara(doc_entry: int) -> dict | None:
    """Estat actual de l'albara llegit de SAP, o None si no existeix."""
    try:
        d = client()._get(f"DeliveryNotes({int(doc_entry)})?$select={_SELECT}")
    except SLNotFoundError:
        return None
    linies = d.get("DocumentLines") or []
    return {
        "docentry": int(d["DocEntry"]),
        "docnum": int(d["DocNum"]),
        "carrega": int(d["U_SEIOrdCargId"]) if d.get("U_SEIOrdCargId") is not None else None,
        "usuari": int(d["UserSign"]) if d.get("UserSign") is not None else None,
        "obert": d.get("DocumentStatus") == "bost_Open",
        "cancelat": d.get("CancelStatus") in ("csYes", "csCancellation"),
        "linies_tancades": sum(1 for l in linies if l.get("LineStatus") != "bost_Open"),
    }


def motiu_no_cancelable(estat: dict, usuaris_sga: set[int]) -> str | None:
    """Per que no es pot cancel·lar des de l'app, o None si es pot."""
    if estat["cancelat"]:
        return "Aquest albarà ja està cancel·lat."
    if estat["usuari"] not in usuaris_sga:
        return "Només es poden cancel·lar des d'aquí els albarans fets pel magatzem (SGA). Aquest s'ha de cancel·lar a SAP."
    if not estat["obert"] or estat["linies_tancades"]:
        return "Aquest albarà ja està facturat o té una devolució. S'ha de gestionar a SAP."
    return None


def cancelar_albara(doc_entry: int) -> None:
    """Cancel·la l'albara. Llença SLError amb el missatge de SAP si no pot.

    El client reintenta els 5xx, i un timeout no diu si SAP ha arribat a
    cancel·lar. En tots dos casos tornem a llegir l'estat: si l'albara ja surt
    cancel·lat, la cancel·lacio s'ha fet i no es un error.
    """
    try:
        client()._request("POST", f"DeliveryNotes({int(doc_entry)})/Cancel")
        return
    except (SLError, requests.RequestException) as e:
        error = e
    try:
        estat = estat_albara(doc_entry)
    except (SLError, requests.RequestException):
        estat = None
    if estat and estat["cancelat"]:
        log.warning("Cancel de l'albara %s ha donat error pero SAP el mostra cancel·lat: %s",
                    doc_entry, error)
        return
    if isinstance(error, SLError):
        raise error
    raise SLError(f"Fallada de xarxa al Service Layer: {error}") from error


def missatge_sap(e: SLError) -> str:
    """El text de l'error que torna SAP (`error.message.value`), si n'hi ha."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        msg = (body.get("error") or {}).get("message")
        if isinstance(msg, dict):
            msg = msg.get("value")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()[:300]
    return ""
