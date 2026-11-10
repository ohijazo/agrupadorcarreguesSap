"""Expedicio d'una agrupacio segons el pistolejat de l'SGA (informatiu).

Agrupar es per PRODUIR i pistolejar es per EXPEDIR. La produccio es marca a
ma (`productes_preparats`, `agrupacions_store.marca_producte`); aqui nomes es
calcula com va el pistolejat (`dades/pistolejat.py:progres_agrupacio`) i se'n
desa el % (`agrupacions.pct_pistolejat`) per mostrar-lo a les llistes. Aquest
modul NO toca les marques de produccio.

Ho fan servir l'endpoint `/api/agrupacions/<id>/pistolejat` (pantalla de
preparacio oberta) i `scripts/sincronitzar_pistolejat.py` (timer).
"""
from __future__ import annotations

import logging
import time
from threading import Lock

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
        "pistolejats_cancelats": [p for p in dades.get("pistolejats_cancelats") or []
                                  if int(p["comanda"]) in docs],
        "estats": {k: v for k, v in (dades.get("estats") or {}).items() if int(k) in docs},
    }


def progres_i_sincronitza(obj: dict) -> dict:
    """Pistolejat d'una agrupacio. Si no esta tancada a ma, en desa el %."""
    dades = obtenir_dades_pistolejat(ids_carregues(obj), incloure_tancades=True)
    progres = calc.progres_agrupacio(obj.get("resultat") or {}, dades)
    if not obj.get("finalitzada_manual_at"):
        agrupacions_store.desa_pct_pistolejat(obj["id"], progres["percent"])
    return progres


# Diverses tablets amb la mateixa agrupacio oberta (cadascuna refresca cada
# 15 s) han de fer una sola consulta a SAP: el resultat d'una agrupacio es
# reaprofita durant uns segons. Es per proces; amb dos workers, com a molt
# dues consultes per finestra.
CACHE_S = 10
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = Lock()


def progres_amb_cache(obj: dict) -> dict:
    """`progres_i_sincronitza` amb una cache curta per agrupacio."""
    ara = time.monotonic()
    with _cache_lock:
        hit = _cache.get(obj["id"])
        if hit and ara - hit[0] < CACHE_S:
            return hit[1]
    progres = progres_i_sincronitza(obj)
    with _cache_lock:
        _cache[obj["id"]] = (time.monotonic(), progres)
        for k in [k for k, (t, _) in _cache.items() if ara - t > 10 * CACHE_S]:
            del _cache[k]
    return progres


def sincronitza_totes(dies: int = 30) -> dict:
    """Una sola consulta a SAP per a totes les agrupacions vives i, despres,
    el % pistolejat de cadascuna. Retorna un resum per al log."""
    objs = agrupacions_store.llistar_per_sincronitzar(dies)
    ids = sorted({i for o in objs for i in ids_carregues(o)})
    if not ids:
        return {"agrupacions": 0, "canviades": 0}
    dades = obtenir_dades_pistolejat(ids, incloure_tancades=True)
    canviades = 0
    for o in objs:
        progres = calc.progres_agrupacio(o["resultat"], _dades_de(dades, set(ids_carregues(o))))
        if agrupacions_store.desa_pct_pistolejat(o["id"], progres["percent"]):
            canviades += 1
            log.info("pistolejat agrupacio=%s percent=%s", o["id"], progres["percent"])
    return {"agrupacions": len(objs), "canviades": canviades}
