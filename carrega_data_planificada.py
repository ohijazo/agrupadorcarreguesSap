"""Stub SAP — no cal snapshot/override de data planificada.

A la variant KAIS aquest modul salvava `car_fecsalida` abans que KAIS la
sobreescrivis quan la carrega passava a estat Sortida. SAP B1 no fa aquesta
sobreescriptura (U_SEIDataS es una data introduida manualment i estable),
per tant no cal cap manteniment local.

Les funcions es mantenen com a no-op per no trencar imports existents des de
`consultes_carregues.py` i `app.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable


def upsert_snapshots(items: list[dict]) -> None:
    return None


def aplicar(items: list[dict]) -> None:
    return None


def get_data_planificada(carrega_ids: Iterable[str]) -> dict[str, datetime]:
    return {}


def snapshot_stats() -> dict:
    return {"snapshots": 0, "overrides": 0}


def llistar_overrides() -> list[dict]:
    return []


def set_override(carrega_id: str, dt: datetime, motiu: str, user_id: int | None = None) -> None:
    return None


def delete_override(carrega_id: str) -> None:
    return None
