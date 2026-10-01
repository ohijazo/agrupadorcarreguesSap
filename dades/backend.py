"""Tria de backend de dades de SAP: SQL Server directe o Service Layer.

Motiu de l'existencia d'aquest modul: SAP no suporta llegir les seves taules
per SQL directe, i estem migrant les lectures al Service Layer. Mentre dura la
migracio les dues implementacions conviuen i es commuten per variable
d'entorn, de manera que revertir es editar el .env i reiniciar el servei
(no cal desplegar codi).

Variables (es llegeixen a CADA crida, no a l'import, perque el revert sigui
immediat amb un `systemctl restart`):

    SAP_BACKEND=sql|sl                  Backend global. Per defecte `sql`.
    SAP_BACKEND_<FUNCIO>=sql|sl         Sobreescriptura per funcio, amb el nom
                                        de la funcio en majuscules. Exemple:
                                        SAP_BACKEND_LLISTAR_TRANSPORTISTES=sl
    SAP_BACKEND_FALLBACK=off|sql        Si el Service Layer falla, reintenta
                                        per SQL. Per defecte `off`.

El fallback es una xarxa de seguretat per als primers dies de cada commutacio,
pero amaga els defectes del backend nou: per aixo comptem els cops que salta i
ho exposem a /health. Sense aquest comptador, una implementacio SL que falli un
terc de les vegades sembla que funcioni perfectament.
"""
from __future__ import annotations

import logging
import os
import threading

import pyodbc

try:  # L'app germana aporta el client del Service Layer via PREPARACIO_PATH.
    from sap_service_layer import SLError  # type: ignore
except ImportError:  # pragma: no cover
    SLError = None  # type: ignore

log = logging.getLogger("agrupacio")

SQL = "sql"
SL = "sl"

# Excepcions que els endpoints han de traduir a 503 "error de base de dades".
# SLError no hereta de pyodbc.Error: sense incloure-la, una fallada del Service
# Layer cauria al except genèric i donaria 500 en lloc de 503.
ERRORS_DADES: tuple[type[BaseException], ...] = (
    (pyodbc.Error,) + ((SLError,) if SLError is not None else ())
)

# Comptador de fallbacks per funcio, per exposar-lo a /health.
_fallbacks: dict[str, int] = {}
_fallbacks_lock = threading.Lock()


def backend_de(funcio: str) -> str:
    """Retorna `sql` o `sl` per a una funcio de dades concreta."""
    especific = os.environ.get(f"SAP_BACKEND_{funcio.upper()}")
    valor = (especific or os.environ.get("SAP_BACKEND") or SQL).strip().lower()
    return valor if valor in (SQL, SL) else SQL


def fallback_actiu() -> bool:
    return (os.environ.get("SAP_BACKEND_FALLBACK") or "off").strip().lower() == SQL


def comptador_fallbacks() -> dict[str, int]:
    with _fallbacks_lock:
        return dict(_fallbacks)


def _registra_fallback(funcio: str) -> None:
    with _fallbacks_lock:
        _fallbacks[funcio] = _fallbacks.get(funcio, 0) + 1


def backends_actius(funcions: list[str]) -> dict[str, str]:
    """Mapa funcio -> backend. Per a /health: davant d'una incidencia cal poder
    saber si s'esta llegint per SQL o per SL sense entrar al servidor."""
    return {f: backend_de(f) for f in funcions}


def despatxa(funcio: str, impl_sql, impl_sl, *args, **kwargs):
    """Executa la implementacio que toca, amb fallback opcional a SQL.

    `impl_sl` pot ser None mentre una funcio encara no estigui migrada: en
    aquest cas s'usa SQL encara que l'entorn demani `sl`, i es deixa constancia
    al log. Aixo permet anar afegint funcions SL sense tocar la facana.
    """
    if backend_de(funcio) == SL:
        if impl_sl is None:
            log.warning("backend: %s demanat per SL pero encara no migrat; uso SQL", funcio)
        else:
            try:
                return impl_sl(*args, **kwargs)
            except Exception:
                if not fallback_actiu():
                    raise
                _registra_fallback(funcio)
                log.warning("backend: %s ha fallat per SL, caic a SQL", funcio, exc_info=True)
    return impl_sql(*args, **kwargs)
