"""Progres de la preparacio d'una agrupacio a partir del pistolejat de l'SGA.

Substitueix el checklist manual: el que diu si un producte esta fet es
`@SEIOPIC` i les linies de comanda de SAP (vegeu `dades/pistolejat.py`), i el
resultat es desa a `productes_preparats` perque el llistat de magatzem, el
Control d'agrupacions i la planificacio continuin funcionant igual.

Ho fan servir l'endpoint `/api/agrupacions/<id>/pistolejat` (pantalla de
preparacio oberta) i `scripts/sincronitzar_pistolejat.py` (timer).
"""
from __future__ import annotations

import logging

import agrupacions_store
from consultes_carregues import obtenir_dades_pistolejat
from dades import pistolejat as calc

log = logging.getLogger("agrupacio")


def ids_carregues(obj: dict) -> list[int]:
    """DocEntry de `@SEI_ORDENCARGA` de les carregues de l'agrupacio."""
    ids = []
    for c in obj.get("carregues") or []:
        try:
            ids.append(int(c.get("car_numero")))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


def _dades_de(dades: dict, ids: set[int]) -> dict:
    """Retalla les dades d'un lot d'agrupacions a les carregues d'una sola."""
    comandes = [c for c in dades.get("comandes") or [] if int(c["carrega"]) in ids]
    docs = {int(c["docentry"]) for c in comandes}
    return {
        "comandes": comandes,
        "pistolejats": [p for p in dades.get("pistolejats") or [] if int(p["comanda"]) in docs],
        "estats": {k: v for k, v in (dades.get("estats") or {}).items() if int(k) in docs},
    }


def progres_i_sincronitza(obj: dict) -> dict:
    """Progres d'una agrupacio. Si no esta tancada a ma, en desa els fets."""
    dades = obtenir_dades_pistolejat(ids_carregues(obj), incloure_tancades=True)
    progres = calc.progres_agrupacio(obj.get("resultat") or {}, dades)
    if not obj.get("finalitzada_manual_at"):
        agrupacions_store.sincronitza_preparats(obj["id"], progres["fets"], progres["percent"])
    return progres


def sincronitza_totes(dies: int = 30) -> dict:
    """Una sola consulta a SAP per a totes les agrupacions vives i, despres,
    la sincronitzacio de cadascuna. Retorna un resum per al log."""
    objs = agrupacions_store.llistar_per_sincronitzar(dies)
    ids = sorted({i for o in objs for i in ids_carregues(o)})
    if not ids:
        return {"agrupacions": 0, "canviades": 0}
    dades = obtenir_dades_pistolejat(ids, incloure_tancades=True)
    canviades = 0
    for o in objs:
        progres = calc.progres_agrupacio(o["resultat"], _dades_de(dades, set(ids_carregues(o))))
        canvis = agrupacions_store.sincronitza_preparats(o["id"], progres["fets"], progres["percent"])
        if canvis and (canvis["afegits"] or canvis["trets"] or canvis["percent_canviat"]):
            canviades += 1
            log.info("pistolejat agrupacio=%s afegits=%s trets=%s percent=%s",
                     o["id"], canvis["afegits"], canvis["trets"], progres["percent"])
    return {"agrupacions": len(objs), "canviades": canviades}
