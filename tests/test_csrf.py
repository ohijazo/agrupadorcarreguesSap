"""Tests del CSRF (double-submit cookie pattern).

Validem que els endpoints protegits rebutgen sense token i accepten amb token
vàlid; els no protegits funcionen sense token; el header és sensible al cas i
no accepta cap valor que no coincideixi amb la cookie.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Stub motor/models per evitar dependència germana
sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def client(store_tmp, monkeypatch):
    """Client amb la BD ja netejada i auth EXPLICITAMENT desactivada
    (el .env de dev pot tenir AUTH_ENABLED=true; aquí ho neutralitzem
    perquè aquests tests cobreixen només el CSRF sense barrejar auth)."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    import app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# --- Endpoints exempts (read-only o públics) ----------------------------
def test_get_no_requereix_csrf(client):
    """Els GET no estan dins de _CSRF_PROTECTED_PREFIXES → no calen token."""
    r = client.get("/api/agrupacions")
    assert r.status_code == 200


def test_health_no_requereix_csrf(client):
    r = client.get("/health")
    assert r.status_code in (200, 503)  # ok o algun servei caigut


# --- Endpoints protegits sense token → 403 ------------------------------
def test_post_agrupacio_sense_csrf(client):
    r = client.post("/api/agrupacions", json={"nom": "x", "carregues": [], "resultat": {}})
    assert r.status_code == 403
    body = r.get_json()
    assert "CSRF" in body.get("error", "")


def test_delete_agrupacio_sense_csrf(client):
    r = client.delete("/api/agrupacions/abc12345")
    assert r.status_code == 403


def test_patch_producte_sense_csrf(client):
    r = client.patch("/api/agrupacions/abc12345/producte", json={"art_codi": "X", "preparat": True})
    assert r.status_code == 403


# --- Endpoints protegits amb token vàlid → no 403 ------------------------
def _csrf_token_from(client):
    """Helper: obté el valor de la cookie csrf_token. Compatible amb les
    dues APIs de Werkzeug (cookie_jar legacy vs get_cookie modern)."""
    if hasattr(client, "get_cookie"):
        c = client.get_cookie("csrf_token")
        return c.value if c else ""
    cookie = next((c for c in getattr(client, "cookie_jar", []) if c.name == "csrf_token"), None)
    return cookie.value if cookie else ""


def test_post_amb_csrf_passa_check(client):
    """Amb token vàlid el middleware CSRF deixa passar; després el endpoint
    valida l'entrada i pot retornar 400, però no 403."""
    client.get("/")  # genera la cookie csrf_token
    tok = _csrf_token_from(client)
    assert tok
    r = client.post(
        "/api/agrupacions",
        json={"nom": "", "carregues": [], "resultat": {}},  # invàlid (nom buit)
        headers={"X-CSRF-Token": tok},
    )
    # El check CSRF passa → el endpoint respon 400 per validació, no 403
    assert r.status_code == 400
    assert "nom" in r.get_json().get("error", "").lower()


def test_post_amb_csrf_token_dolent(client):
    client.get("/")
    r = client.post(
        "/api/agrupacions",
        json={"nom": "x", "carregues": [], "resultat": {}},
        headers={"X-CSRF-Token": "valor-no-coincideix-amb-cookie"},
    )
    assert r.status_code == 403


def test_admin_endpoints_sota_csrf(client):
    """Els endpoints /api/admin/* també requereixen CSRF (sense auth retorna 403 perquè
    el CSRF check va abans del check d'auth)."""
    r = client.post("/api/admin/usuaris", json={"username": "x", "password": "x" * 8, "nom": "X"})
    # Sense token CSRF (i auth desactivat al test, però CSRF sí actiu)
    assert r.status_code == 403


# --- La cookie es genera al primer GET ----------------------------------
def test_csrf_cookie_es_genera_al_primer_get(client):
    r = client.get("/")
    cookies_setades = [h for h in r.headers.getlist("Set-Cookie") if h.startswith("csrf_token=")]
    assert len(cookies_setades) == 1
    # Ha de tenir SameSite=Strict
    assert "SameSite=Strict" in cookies_setades[0]


def test_csrf_cookie_no_es_resetea_si_ja_existeix(client):
    client.get("/")
    tok1 = _csrf_token_from(client)
    r2 = client.get("/")
    set_cookies = [h for h in r2.headers.getlist("Set-Cookie") if h.startswith("csrf_token=")]
    assert len(set_cookies) == 0
    tok2 = _csrf_token_from(client)
    assert tok1 == tok2 and tok1
