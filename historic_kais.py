"""Historic de carregues de KAIS (els tres mesos abans del 23/11/2026).

Copia congelada que `scripts/importar_historic_kais.py` desa a
`historic_carregues` el dia del canvi (vegeu db/migrations/009). El calendari
la barreja amb les carregues de SAP perque l'usuari continui veient les
d'abans com les veia a l'app de KAIS. Els ids no es poden confondre: els de
SAP comencen per "SAP/" i els de KAIS per l'any ("2026/...").
"""
import logging

import db

log = logging.getLogger("agrupacio")


def es_kais(eje: str | None) -> bool:
    return bool(eje) and str(eje) != "SAP"


def carregues(desde: str, fins: str, tra_codis: list[str] | None = None) -> list[dict]:
    """Items de /api/carregues de KAIS amb data entre `desde` i `fins` (inclosos)."""
    try:
        files = db.fetch_all(
            "SELECT item FROM historic_carregues WHERE data_cal BETWEEN %s AND %s "
            "ORDER BY data_cal, carrega_id", (desde, fins))
    except Exception:
        # Sense historic (taula no creada o PG caigut) el calendari de SAP ha
        # de continuar funcionant.
        log.exception("historic_kais: no s'ha pogut llegir l'historic")
        return []
    items = [f["item"] for f in files]
    if tra_codis:
        items = [it for it in items if (it.get("tra_codi") or "") in tra_codis]
    return items


def detall(carrega_id: str) -> dict | None:
    f = db.fetch_one("SELECT detall FROM historic_carregues WHERE carrega_id = %s", (carrega_id,))
    return f["detall"] if f else None
