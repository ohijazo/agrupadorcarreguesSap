"""Tests del mòdul auth.py — hashing, decoradors i flow de login.

Requereix PG_HOST (els decoradors fan SELECT a `usuaris`).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import auth


# --- hash_password / verify_password (sense PG) --------------------------
def test_hash_password_format():
    h = auth.hash_password("hola1234")
    parts = h.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) >= 100_000  # iter alts


def test_hash_password_diferent_cada_vegada():
    """Salt aleatori: dos hashes de la mateixa password han de ser diferents."""
    h1 = auth.hash_password("hola1234")
    h2 = auth.hash_password("hola1234")
    assert h1 != h2


def test_verify_password_correcte():
    h = auth.hash_password("Secret!2026")
    assert auth.verify_password("Secret!2026", h) is True


def test_verify_password_incorrecte():
    h = auth.hash_password("Secret!2026")
    assert auth.verify_password("secret!2026", h) is False  # case-sensitive
    assert auth.verify_password("", h) is False
    assert auth.verify_password("Secret!2026", "") is False
    assert auth.verify_password("Secret!2026", "garbage") is False


def test_hash_password_buida_llanca():
    with pytest.raises(ValueError):
        auth.hash_password("")


def test_verify_password_format_invalid():
    """Hashes amb format incorrecte han de retornar False, no llançar."""
    assert auth.verify_password("abc", "no_te_dollars") is False
    assert auth.verify_password("abc", "algo$1$dolent") is False
    assert auth.verify_password("abc", "wrong_algo$1000$salt$hash") is False


# --- CRUD usuaris (necessita PG) ----------------------------------------
@pytest.fixture
def usuaris_tmp():
    if not os.environ.get("PG_HOST"):
        pytest.skip("PG_HOST no configurat")
    import db
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuaris WHERE username LIKE '%@pytest.local'")
    yield
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuaris WHERE username LIKE '%@pytest.local'")


def test_crear_usuari_ok(usuaris_tmp):
    u = auth.crear_usuari("one@pytest.local", "secret123", "Test One")
    assert u["username"] == "one@pytest.local"
    assert u["rol"] == "oficina"
    assert u["actiu"] is True


def test_crear_usuari_rol_admin(usuaris_tmp):
    u = auth.crear_usuari("admin@pytest.local", "secret123", "Test Admin", rol="admin")
    assert u["rol"] == "admin"


def test_crear_usuari_username_invalid(usuaris_tmp):
    with pytest.raises(ValueError):
        auth.crear_usuari("", "secret123", "Test")
    with pytest.raises(ValueError):
        auth.crear_usuari("no es un email", "secret123", "Test")
    with pytest.raises(ValueError):
        auth.crear_usuari("nomesun_nom", "secret123", "Test")
    with pytest.raises(ValueError):
        auth.crear_usuari("falta@domini", "secret123", "Test")


def test_crear_usuari_rol_invalid(usuaris_tmp):
    with pytest.raises(ValueError):
        auth.crear_usuari("x@pytest.local", "secret123", "X", rol="superhero")


def test_get_user_by_username_inexistent(usuaris_tmp):
    assert auth.get_user_by_username("noexisteix@pytest.local") is None


def test_get_user_by_username_normalitza(usuaris_tmp):
    auth.crear_usuari("two@pytest.local", "secret123", "Test Two")
    u = auth.get_user_by_username("  TWO@PYTEST.LOCAL  ")  # majúscules i espais
    assert u is not None
    assert u["username"] == "two@pytest.local"


def test_actualitzar_usuari_nom_rol(usuaris_tmp):
    u = auth.crear_usuari("three@pytest.local", "secret123", "Nom Antic")
    u2 = auth.actualitzar_usuari(u["id"], nom="Nom Nou", rol="admin")
    assert u2["nom"] == "Nom Nou"
    assert u2["rol"] == "admin"


def test_actualitzar_usuari_desactivar(usuaris_tmp):
    u = auth.crear_usuari("four@pytest.local", "secret123", "Test Four")
    u2 = auth.actualitzar_usuari(u["id"], actiu=False)
    assert u2["actiu"] is False


def test_actualitzar_usuari_inexistent(usuaris_tmp):
    assert auth.actualitzar_usuari(999999, nom="X") is None


def test_canvi_contrasenya(usuaris_tmp):
    u = auth.crear_usuari("five@pytest.local", "old_password", "Test Five")
    assert auth.canvi_contrasenya(u["id"], "new_password_long") is True
    # Necessitem el password_hash — obtenir_usuari no el retorna, fem query directa
    import db
    row = db.fetch_one("SELECT password_hash FROM usuaris WHERE id = %s", (u["id"],))
    assert auth.verify_password("new_password_long", row["password_hash"]) is True
    assert auth.verify_password("old_password", row["password_hash"]) is False


def test_canvi_contrasenya_massa_curta(usuaris_tmp):
    u = auth.crear_usuari("six@pytest.local", "abc12345", "Test Six")
    with pytest.raises(ValueError):
        auth.canvi_contrasenya(u["id"], "curt")


def test_es_email_valid():
    assert auth.es_email_valid("nom@empresa.com") is True
    assert auth.es_email_valid("a.b@c.de") is True
    assert auth.es_email_valid("nom+tag@empresa.cat") is True
    assert auth.es_email_valid("nom@empresa") is False  # falta TLD
    assert auth.es_email_valid("nom@empresa.c") is False  # TLD massa curt (<2)
    assert auth.es_email_valid("nom.empresa.com") is False  # falta @
    assert auth.es_email_valid("") is False
    assert auth.es_email_valid(None) is False
    assert auth.es_email_valid("amb espai@empresa.com") is False


# --- auth_enabled --------------------------------------------------------
def test_auth_enabled_per_defecte_false(monkeypatch):
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    assert auth.auth_enabled() is False


def test_auth_enabled_true(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    assert auth.auth_enabled() is True
    monkeypatch.setenv("AUTH_ENABLED", "1")
    assert auth.auth_enabled() is True
    monkeypatch.setenv("AUTH_ENABLED", "yes")
    assert auth.auth_enabled() is True


def test_auth_enabled_false_other_values(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    assert auth.auth_enabled() is False
    monkeypatch.setenv("AUTH_ENABLED", "0")
    assert auth.auth_enabled() is False
    monkeypatch.setenv("AUTH_ENABLED", "")
    assert auth.auth_enabled() is False


def test_crear_usuari_rol_granel(usuaris_tmp):
    u = auth.crear_usuari("granel@pytest.local", "secret123", "Granel", rol="granel")
    assert u["rol"] == "granel"
