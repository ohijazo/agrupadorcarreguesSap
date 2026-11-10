"""Tests de /api/agrupacions/version (polling lleuger).

El comptador augmenta cada cop que es desa, elimina, o es marca un producte.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def client(store_tmp, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    import app as app_module
    with app_module.app.test_client() as c:
        yield c


def _csrf_token(client):
    client.get("/")
    if hasattr(client, "get_cookie"):
        c = client.get_cookie("csrf_token")
        return c.value if c else ""
    return next((c.value for c in getattr(client, "cookie_jar", []) if c.name == "csrf_token"), "")


def _carrega(cid="2026/01/0000001"):
    return {"carrega_id": cid, "eje_ejercicio": "2026", "sca_serie": "01", "car_numero": cid.split("/")[-1]}


def _resultat():
    return {"productes": [{"art_codi": "A", "art_descrip": "A"}], "total_palets_fisics": 1, "total_sacs": 5}


def test_version_retorna_int(client):
    r = client.get("/api/agrupacions/version")
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body.get("v"), int)


def test_version_no_canvia_sense_escriptura(client):
    v1 = client.get("/api/agrupacions/version").get_json()["v"]
    v2 = client.get("/api/agrupacions/version").get_json()["v"]
    assert v1 == v2


def test_version_augmenta_al_desar(client):
    tok = _csrf_token(client)
    v1 = client.get("/api/agrupacions/version").get_json()["v"]
    r = client.post(
        "/api/agrupacions",
        json={"nom": "Test polling 1", "carregues": [_carrega()], "resultat": _resultat()},
        headers={"X-CSRF-Token": tok},
    )
    assert r.status_code == 200
    v2 = client.get("/api/agrupacions/version").get_json()["v"]
    assert v2 > v1


def test_version_augmenta_al_eliminar(client):
    tok = _csrf_token(client)
    # Desar
    r = client.post(
        "/api/agrupacions",
        json={"nom": "Test polling 2", "carregues": [_carrega("2026/01/0000002")], "resultat": _resultat()},
        headers={"X-CSRF-Token": tok},
    )
    id_ = r.get_json()["id"]
    v_after_save = client.get("/api/agrupacions/version").get_json()["v"]
    # Eliminar
    client.delete(f"/api/agrupacions/{id_}", headers={"X-CSRF-Token": tok})
    v_after_del = client.get("/api/agrupacions/version").get_json()["v"]
    assert v_after_del > v_after_save


def test_version_augmenta_al_marcar_producte(client):
    tok = _csrf_token(client)
    r = client.post(
        "/api/agrupacions",
        json={"nom": "Test polling 3", "carregues": [_carrega("2026/01/0000003")], "resultat": _resultat()},
        headers={"X-CSRF-Token": tok},
    )
    id_ = r.get_json()["id"]
    v0 = client.get("/api/agrupacions/version").get_json()["v"]
    client.patch(
        f"/api/agrupacions/{id_}/producte",
        json={"art_codi": "A", "preparat": True},
        headers={"X-CSRF-Token": tok},
    )
    v1 = client.get("/api/agrupacions/version").get_json()["v"]
    assert v1 > v0
    # Desmarcar també augmenta
    client.patch(
        f"/api/agrupacions/{id_}/producte",
        json={"art_codi": "A", "preparat": False},
        headers={"X-CSRF-Token": tok},
    )
    v2 = client.get("/api/agrupacions/version").get_json()["v"]
    assert v2 > v1
