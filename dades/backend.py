"""Punt d'entrada al commutador de backend, amb degradacio si no hi es.

El commutador de debo viu a `sl_lectura/backend.py`, a l'app germana, perque el
contracte de variables d'entorn l'han de compartir les dues apps. Aquest modul
nomes el reexporta i, si l'app germana no es al `sys.path`, hi posa un
reemplaçament degenerat que sempre diu SQL.

Per que fa falta la degradacio: sense ella, aquesta app no pot ni arrencar si
`PREPARACIO_PATH` no apunta a l'app germana. I aixo no es nomes un cas
hipotetic — es el que passa a la CI de GitHub, que no te ni `.env` ni l'altre
repositori, i es el que va fer fallar el build del commit 9ccf717.

La degradacio NO es una segona implementacio del contracte: es el cas limit
d'un sol valor possible. Sense l'app germana no hi ha capa de lectura del
Service Layer, i per tant l'unic backend possible es SQL. Tota la logica real
(precedencia de variables, fallback, comptadors) segueix tenint una sola font.
"""
from __future__ import annotations

import logging

log = logging.getLogger("agrupacio")

try:
    from sl_lectura.backend import (  # noqa: F401
        ERRORS_DADES,
        SL,
        SQL,
        backend_de,
        backends_actius,
        comptador_fallbacks,
        despatxa,
        fallback_actiu,
    )
    DISPONIBLE = True

except ImportError:
    import pyodbc

    DISPONIBLE = False
    SQL = "sql"
    SL = "sl"
    ERRORS_DADES: tuple[type[BaseException], ...] = (pyodbc.Error,)

    log.info(
        "sl_lectura no disponible (PREPARACIO_PATH no apunta a l'app germana): "
        "nomes hi haura backend SQL."
    )

    def backend_de(funcio: str) -> str:  # noqa: D103
        return SQL

    def fallback_actiu() -> bool:  # noqa: D103
        return False

    def comptador_fallbacks() -> dict[str, int]:  # noqa: D103
        return {}

    def backends_actius(funcions: list[str]) -> dict[str, str]:  # noqa: D103
        return {f: SQL for f in funcions}

    def despatxa(funcio: str, impl_sql, impl_sl, *args, **kwargs):  # noqa: D103
        return impl_sql(*args, **kwargs)
