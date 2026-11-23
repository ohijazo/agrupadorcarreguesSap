"""Autenticació amb usuaris locals a PostgreSQL.

Format del hash de contrasenya: `pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>`.
Usa `hashlib.pbkdf2_hmac` (built-in, sense dependències externes). El format
inclou l'algorisme i les iteracions perquè es pugui migrar a Argon2/scrypt
al futur sense invalidar els hashes existents.

Sessions amb Flask `session` (cookies signades amb `app.secret_key`).

L'autenticació s'activa amb la variable `AUTH_ENABLED=true` al `.env`. Per
defecte (`false`) l'app continua oberta — útil per a desenvolupament local.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
from functools import wraps


# Validació d'email simple — suficient per al cas d'ús intern. No prentem
# fer un parser RFC 5322 complet; només garantim que té un format raonable
# (X@Y.Z, sense espais).
_RE_EMAIL = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


def es_email_valid(s: str) -> bool:
    return bool(_RE_EMAIL.match((s or "").strip().lower()))

from flask import jsonify, redirect, request, session, url_for

import audit
import db

log = logging.getLogger("agrupacio.auth")

PBKDF2_ITER = 200_000
PBKDF2_ALGO = "sha256"
SALT_BYTES = 16

# 'granel': nomes "Gestió d'albarans", amb els albarans de granel amb transport
# propi; pot imprimir-los pero no cancel·lar-los (app.py, `_es_rol_granel`).
ROL_GRANEL = "granel"
ROLS = ("admin", "oficina", "magatzem", ROL_GRANEL)


def auth_enabled() -> bool:
    return os.environ.get("AUTH_ENABLED", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Hash / verify
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("contrasenya buida")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, plain.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2_sha256${PBKDF2_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(plain: str, stored: str) -> bool:
    if not plain or not stored:
        return False
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac(PBKDF2_ALGO, plain.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------------------
# CRUD usuaris
# ---------------------------------------------------------------------------
def crear_usuari(username: str, password: str, nom: str, rol: str = "oficina") -> dict:
    username = (username or "").strip().lower()
    if not es_email_valid(username):
        raise ValueError("L'usuari ha de ser un email vàlid (p.ex. nom@agrienergia.com)")
    if rol not in ROLS:
        raise ValueError(f"rol invàlid: {rol}")
    h = hash_password(password)
    row = db.fetch_one(
        """
        INSERT INTO usuaris (username, password_hash, nom, rol)
        VALUES (%s, %s, %s, %s)
        RETURNING id, username, nom, rol, actiu, created_at
        """,
        (username, h, nom.strip(), rol),
    )
    audit.log("usuari_creat", target=username, detall={"rol": rol})
    return dict(row)


def get_user_by_username(username: str) -> dict | None:
    return db.fetch_one(
        "SELECT id, username, password_hash, nom, rol, actiu FROM usuaris WHERE username = %s",
        ((username or "").strip().lower(),),
    )


def actualitza_last_login(user_id: int) -> None:
    try:
        db.execute("UPDATE usuaris SET last_login_at = NOW() WHERE id = %s", (user_id,))
    except Exception as e:
        log.warning("No s'ha pogut actualitzar last_login_at: %s", str(e)[:200])


def llistar_usuaris() -> list[dict]:
    return [dict(r) for r in db.fetch_all(
        """
        SELECT id, username, nom, rol, actiu, created_at, last_login_at
        FROM usuaris
        ORDER BY actiu DESC, username
        """
    )]


def obtenir_usuari(id_: int) -> dict | None:
    r = db.fetch_one(
        """
        SELECT id, username, nom, rol, actiu, created_at, last_login_at
        FROM usuaris WHERE id = %s
        """,
        (id_,),
    )
    return dict(r) if r else None


def actualitzar_usuari(id_: int, nom: str | None = None, rol: str | None = None,
                       actiu: bool | None = None) -> dict | None:
    """Actualitza camps mutables. Retorna l'usuari actualitzat o None si no existeix."""
    sets, params = [], []
    if nom is not None:
        nom = nom.strip()
        if not nom:
            raise ValueError("nom buit")
        sets.append("nom = %s")
        params.append(nom)
    if rol is not None:
        if rol not in ROLS:
            raise ValueError(f"rol invàlid: {rol}")
        sets.append("rol = %s")
        params.append(rol)
    if actiu is not None:
        sets.append("actiu = %s")
        params.append(bool(actiu))
    if not sets:
        return obtenir_usuari(id_)
    params.append(id_)
    db.execute(f"UPDATE usuaris SET {', '.join(sets)} WHERE id = %s", tuple(params))
    audit.log(
        "usuari_actualitzat",
        target=str(id_),
        detall={"nom": nom, "rol": rol, "actiu": actiu},
    )
    return obtenir_usuari(id_)


def canvi_contrasenya(id_: int, nova: str) -> bool:
    """Reseteja la contrasenya d'un usuari. Retorna True si OK."""
    if not nova or len(nova) < 8:
        raise ValueError("la contrasenya ha de tenir com a mínim 8 caràcters")
    h = hash_password(nova)
    rows = db.execute("UPDATE usuaris SET password_hash = %s WHERE id = %s", (h, id_))
    if rows:
        audit.log("password_reset", target=str(id_))
        return True
    return False


# ---------------------------------------------------------------------------
# Decoradors
# ---------------------------------------------------------------------------
def requires_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not auth_enabled():
            return fn(*args, **kwargs)
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Autenticació requerida"}), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def requires_rol(*rols):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not auth_enabled():
                return fn(*args, **kwargs)
            if not session.get("user_id"):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Autenticació requerida"}), 401
                return redirect(url_for("login", next=request.path))
            if session.get("user_rol") not in rols:
                return jsonify({"error": "Permisos insuficients"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return deco
