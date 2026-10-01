"""Cache en memoria del mestre d'articles llegit pel Service Layer.

Per que fa falta: `palletitzable` i `is_granel` depenen de la unitat de venda
de l'article (`OITM.SalUnitMsr`, que al Service Layer es `Items.SalesUnit`), i
el Service Layer no permet cap JOIN ni cap filtre sobre linies de document.
Sense aquest mapa, cada calcul d'aquests dos camps necessitaria una consulta
d'articles per pagina de llistat.

El mestre son ~2.000 articles i es gairebe estatic: portar-se'l sencer son 2-3
crides i unes poques centenes de KB. Es per worker (amb 2 workers hi ha 2
copies); la divergencia es irrellevant perque es nomes lectura de dades que
amb prou feines canvien.

Un article nou que aparegui a SAP no ha de quedar invisible fins que caduqui la
cache: els codis que no hi son es consulten en viu i es memoritzen.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from dades.sl import odata as q
from dades.sl.client import client

log = logging.getLogger("agrupacio")

ARTICLES = "Items"
_CAMPS = "ItemCode,ItemName,SalesUnit"

_mapa: dict[str, dict] | None = None
_carregat_a: float = 0.0
_lock = threading.Lock()


def _ttl() -> float:
    return float(os.environ.get("SAP_SL_CACHE_ARTICLES_TTL", "900"))


def _normalitza(f: dict) -> tuple[str, dict]:
    codi = (f.get("ItemCode") or "").strip()
    return codi, {
        "art_descrip": (f.get("ItemName") or "").strip(),
        "unitat_venda": (f.get("SalesUnit") or "").strip(),
    }


def mapa(refresca: bool = False) -> dict[str, dict]:
    """Mapa `ItemCode -> {art_descrip, unitat_venda}` de tot el mestre."""
    global _mapa, _carregat_a
    with _lock:
        caducat = _mapa is None or (time.monotonic() - _carregat_a) > _ttl()
        if refresca or caducat:
            t = time.monotonic()
            files = client().tot(ARTICLES, select=_CAMPS, ordre="ItemCode")
            _mapa = dict(_normalitza(f) for f in files)
            _carregat_a = time.monotonic()
            log.info("cache d'articles: %d articles en %.0f ms",
                     len(_mapa), (_carregat_a - t) * 1000)
        return _mapa


def consulta(codis) -> dict[str, dict]:
    """Dades dels codis demanats, servides de la cache.

    Els codis que no hi son es consulten en viu i s'afegeixen al mapa, perque
    un article creat fa un moment a SAP no ha de ser invisible fins que la
    cache caduqui.
    """
    m = mapa()
    trobats = {c: m[c] for c in codis if c in m}
    falten = [c for c in codis if c not in m]
    if not falten:
        return trobats

    c = client()
    nous: dict[str, dict] = {}
    for tros in q.trossos(falten):
        for f in c.tot(ARTICLES, select=_CAMPS, filtre=q.qualsevol_de("ItemCode", tros)):
            codi, dades = _normalitza(f)
            nous[codi] = dades
    if nous:
        with _lock:
            if _mapa is not None:
                _mapa.update(nous)
        log.info("cache d'articles: %d codis afegits en viu", len(nous))
    trobats.update(nous)
    return trobats


def unitats_venda(codis) -> dict[str, str]:
    """Mapa `ItemCode -> unitat de venda` per als codis demanats."""
    return {c: d["unitat_venda"] for c, d in consulta(codis).items()}


def invalida() -> None:
    global _mapa
    with _lock:
        _mapa = None
