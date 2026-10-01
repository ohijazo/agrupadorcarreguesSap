"""Facana de les consultes de carregues contra SAP B1.

La implementacio real viu a `dades/`: `dades/sql/carregues.py` (SQL Server
directe, la de sempre) i `dades/sl/carregues.py` (Service Layer, en migracio).
Aquest modul manté la mateixa superficie d'import que tenia abans, aixi que
`app.py` i `agregador.py` no s'han de tocar per commutar de backend.

Quin backend s'usa el decideix `dades/backend.py` a partir del .env. Vegeu-hi
la documentacio de les variables `SAP_BACKEND*`.
"""
from __future__ import annotations

import os

# --- Carrega .env local -------------------------------------------------
# Es manté aqui (i no nomes a app.py) perque hi ha scripts que importen
# aquest modul directament. Els submoduls de dades/ confien que l'entorn
# ja estigui carregat quan s'importen.
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from dades import backend as _b  # noqa: E402
from dades.sql import carregues as _sql  # noqa: E402

# Implementacio Service Layer: encara no existeix cap funcio migrada. A mesura
# que es migrin, aqui s'anira important `dades.sl.carregues` i es passara al
# `despatxa` corresponent. Mentre val None, `despatxa` usa SQL sempre.
try:  # pragma: no cover
    from dades.sl import carregues as _sl  # type: ignore
except ImportError:  # pragma: no cover
    _sl = None  # type: ignore

# Noms de les funcions de dades, per a /health i per al comptador de fallbacks.
FUNCIONS = [
    "llistar_carregues",
    "llistar_estats_carregues",
    "llistar_transportistes",
    "cercar_articles",
    "obtenir_descrip_articles",
    "obtenir_comandes_carrega",
    "resum_carrega",
]


def _impl_sl(nom: str):
    return getattr(_sl, nom, None) if _sl is not None else None


# `connectar` NO passa pel commutador: es la connexio a SQL Server i la
# necessiten /health i els scripts de diagnostic, independentment del backend.
# Tambe la necessita el motor d'embalatges de l'app germana, que seguira
# llegint per SQL fins que es migri (vegeu el pla de migracio).
connectar = _sql.connectar


def llistar_carregues(*args, **kwargs):
    return _b.despatxa("llistar_carregues", _sql.llistar_carregues,
                       _impl_sl("llistar_carregues"), *args, **kwargs)


def llistar_estats_carregues(*args, **kwargs):
    return _b.despatxa("llistar_estats_carregues", _sql.llistar_estats_carregues,
                       _impl_sl("llistar_estats_carregues"), *args, **kwargs)


def llistar_transportistes(*args, **kwargs):
    return _b.despatxa("llistar_transportistes", _sql.llistar_transportistes,
                       _impl_sl("llistar_transportistes"), *args, **kwargs)


def cercar_articles(*args, **kwargs):
    return _b.despatxa("cercar_articles", _sql.cercar_articles,
                       _impl_sl("cercar_articles"), *args, **kwargs)


def obtenir_descrip_articles(*args, **kwargs):
    return _b.despatxa("obtenir_descrip_articles", _sql.obtenir_descrip_articles,
                       _impl_sl("obtenir_descrip_articles"), *args, **kwargs)


def obtenir_comandes_carrega(*args, **kwargs):
    return _b.despatxa("obtenir_comandes_carrega", _sql.obtenir_comandes_carrega,
                       _impl_sl("obtenir_comandes_carrega"), *args, **kwargs)


def resum_carrega(*args, **kwargs):
    return _b.despatxa("resum_carrega", _sql.resum_carrega,
                       _impl_sl("resum_carrega"), *args, **kwargs)
