"""Fixtures compartides de pytest.

La majoria de tests del store i dels endpoints necessiten una BD PostgreSQL
de test. Si no hi ha `PG_HOST` definit a l'entorn, els tests es marquen com
`skip` automàticament.

Per executar els tests:
    1) Tenir un Postgres local
    2) Crear una BD `agrupaciocarregues_test` (separada de la real!)
    3) Aplicar `db/schema.sql`
    4) export PG_HOST=localhost PG_DATABASE=agrupaciocarregues_test PG_USER=... PG_PASSWORD=...
    5) pytest tests/
"""
from __future__ import annotations

import os
import sys

import pytest

# Permet importar des de l'arrel del repo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _bd_de_test() -> bool:
    """Els tests amb PostgreSQL fan TRUNCATE de `agrupacions`: només es poden
    executar contra una BD que es digui *_test. No n'hi ha prou amb PG_HOST,
    perquè qualsevol import de l'app (app.py, consultes_carregues) carrega el
    .env de desenvolupament a os.environ. El 9-11-2026 això va fer que els
    tests buidessin `agrupaciocarregues_sap_dev`."""
    return bool(os.environ.get("PG_HOST")) and os.environ.get("PG_DATABASE", "").endswith("_test")


_NEEDS_PG = pytest.mark.skipif(
    not _bd_de_test(),
    reason="Cal PG_HOST i una BD *_test per a tests amb PostgreSQL"
)


@pytest.fixture
def store_tmp(monkeypatch):
    """Neteja les taules abans i després de cada test.

    Manté el nom 'store_tmp' per compatibilitat amb els tests existents,
    encara que ara no usa un directori tmp.
    """
    # Es torna a mirar aquí (i no només en recollir els tests) perquè el .env
    # es pot haver carregat entremig. Mai TRUNCATE fora d'una BD *_test.
    if not _bd_de_test():
        pytest.skip("Cal una BD de test (PG_DATABASE=*_test)")
    import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            nom_bd = cur.fetchone()
    nom_bd = nom_bd[0] if isinstance(nom_bd, tuple) else nom_bd["current_database"]
    if not str(nom_bd).endswith("_test"):
        pytest.skip(f"La connexió apunta a {nom_bd}, que no és una BD de test")
    import agrupacions_store

    # Reseteja el cache d'índex en memòria
    agrupacions_store._clear_local_cache()

    # Buida les taules (CASCADE neteja les filles automàticament)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE agrupacions CASCADE")

    yield

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE agrupacions CASCADE")
    agrupacions_store._clear_local_cache()


# Marca tot el mòdul tests/test_agrupacions_store i tests/test_endpoints com a NEEDS_PG
def pytest_collection_modifyitems(config, items):
    if _bd_de_test():
        return
    needs_pg_modules = {"test_agrupacions_store", "test_endpoints", "test_csrf", "test_admin", "test_polling"}
    skip_marker = pytest.mark.skip(reason="Cal PG_HOST i una BD *_test")
    for item in items:
        module = item.module.__name__.rsplit(".", 1)[-1] if hasattr(item, "module") else ""
        if module in needs_pg_modules:
            item.add_marker(skip_marker)
