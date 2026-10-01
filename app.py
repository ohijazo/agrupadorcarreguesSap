"""Flask app — Agrupació de càrregues.

Endpoints:
    GET  /                    interfície principal
    GET  /api/transportistes  llistat transportistes (últim any)
    GET  /api/carregues       llistat càrregues filtrades
    POST /api/agrupar         agrupar càrregues seleccionades
"""
import logging
import os
import secrets
import sys
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from logging.handlers import RotatingFileHandler
from threading import Lock

from flask import Flask, jsonify, make_response, redirect, render_template, request, send_from_directory, session, url_for

# --- Bootstrap .env i sys.path ABANS d'importar agregador ----------------
_HERE = os.path.dirname(os.path.abspath(__file__))


def _carregar_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# 1) .env local (si existeix) — pot definir PREPARACIO_PATH i overrides
_carregar_env(os.path.join(_HERE, ".env"))

# 2) Resol PREPARACIO_PATH (env > default)
_PREP_PATH = os.environ.get("PREPARACIO_PATH", r"P:\preparacioComandesVenda")

# 3) Fallback: carrega .env de l'app germana per heretar credencials SQL
#    (evita duplicar secrets en dos directoris)
_carregar_env(os.path.join(_PREP_PATH, ".env"))

if _PREP_PATH and os.path.isdir(_PREP_PATH) and _PREP_PATH not in sys.path:
    sys.path.insert(0, _PREP_PATH)

# Imports locals (després del sys.path)
from agregador import agrupar, serialitzar  # noqa: E402
from consultes_carregues import (  # noqa: E402
    FUNCIONS as FUNCIONS_DADES, cercar_articles, connectar, llistar_carregues,
    llistar_estats_carregues, llistar_transportistes, resum_carrega,
)
from dades import backend as backend_dades  # noqa: E402
# Power BI es queda a SQL directe a proposit: pagina fins a 5000 files i per
# Service Layer caldria portar-se les linies de totes les comandes (247 camps
# per linia, ~19 KB per comanda). Import explicit perque l'excepcio es vegi
# al codi i no quedi amagada a la configuracio.
from dades.sql.carregues import llistar_carregues as llistar_carregues_sql  # noqa: E402
from valida import (  # noqa: E402
    valida_codi, valida_int, valida_llista_carregues, valida_rang_dates,
)
import agrupacions_store  # noqa: E402

# --- Logging amb rotació -------------------------------------------------
_log_handler = RotatingFileHandler(
    os.path.join(_HERE, "agrupacio.log"),
    maxBytes=2_000_000, backupCount=5, encoding="utf-8",
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler, _stream_handler])
log = logging.getLogger("agrupacio")

app = Flask(__name__)
# Secret key per a signar les cookies de sessió (auth). En dev acceptem un
# valor random si no està definit; en producció ha d'estar SEMPRE al .env
# (si no, les sessions s'invaliden cada reinici).
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_urlsafe(48)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_NAME="agc_session",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# Import després de configurar `app` per evitar imports circulars amb auth.py
import audit  # noqa: E402
import auth  # noqa: E402


# --- Bootstrap de la taula del comptador de versió -----------------------
# Crea la taula `meta_agrupacions` i la fila (id=1) si no existeixen, perquè
# els workers Gunicorn puguin sincronitzar la cache d'índex via la BD sense
# que l'admin hagi de córrer migracions manuals. Idempotent.
def _bootstrap_meta_agrupacions() -> None:
    import db  # local import: PG pot no estar configurat en certs entorns de test
    if not os.environ.get("PG_HOST"):
        return
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS meta_agrupacions (
                        id      SMALLINT  PRIMARY KEY CHECK (id = 1),
                        version BIGINT    NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute(
                    "INSERT INTO meta_agrupacions (id, version) VALUES (1, 0) "
                    "ON CONFLICT (id) DO NOTHING"
                )
        log.info("meta_agrupacions: taula i fila inicialitzades")
    except Exception:
        log.exception("No s'ha pogut inicialitzar meta_agrupacions")


_bootstrap_meta_agrupacions()


# --- Cache-busting d'assets ----------------------------------------------
@app.context_processor
def _inject_static_helper():
    def static_url(filename: str) -> str:
        path = os.path.join(_HERE, "static", *filename.split("/"))
        try:
            v = int(os.path.getmtime(path))
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)
    return {"static_url": static_url}


# --- Info d'usuari disponible a totes les plantilles ----------------------
@app.context_processor
def _inject_auth_context():
    return {
        "auth_enabled": auth.auth_enabled(),
        "current_user": {
            "username": session.get("user_username"),
            "nom": session.get("user_name"),
            "rol": session.get("user_rol"),
        } if session.get("user_id") else None,
    }


# --- Slow request logging ------------------------------------------------
# Detecta peticions lentes (>500ms) per a poder identificar colls d'ampolla
# sense activar profiling complet. El llindar es pot ajustar amb la variable
# d'entorn SLOW_REQUEST_MS (per defecte 500 = 0.5s).
@app.before_request
def _slow_request_start():
    request._start_time = time.monotonic()


@app.after_request
def _slow_request_log(resp):
    try:
        elapsed_ms = (time.monotonic() - request._start_time) * 1000
        threshold = int(os.environ.get("SLOW_REQUEST_MS", "500"))
        if elapsed_ms >= threshold:
            log.warning(
                "slow request: %d ms · %s %s · status=%d",
                int(elapsed_ms), request.method, request.path, resp.status_code,
            )
    except Exception:
        pass
    return resp


# --- Headers de seguretat ------------------------------------------------
@app.after_request
def secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # No s'emet X-Frame-Options perquè el calendari s'ha d'embeguir
    # via iframe a l'app germana (comandes.agrienergia.local). X-Frame-Options
    # no admet múltiples orígens; els navegadors moderns prioritzen
    # `frame-ancestors` de CSP, que sí ho permet.
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'self' http://comandes.agrienergia.local "
        "http://comandessap.agrienergia.local "
        # Transitori: mentre comandessap.agrienergia.local no resolgui al DNS,
        # l'app de comandes SAP s'obre per IP i port, i aquest es l'origen que
        # veu el navegador. Es pot treure quan el nom estigui en us.
        "http://192.168.11.244:5002 "
        "http://127.0.0.1:5002 http://localhost:5002;"
    )
    return resp


# --- CSRF (double-submit cookie pattern) ----------------------------------
# Per a PATCH/POST/DELETE als endpoints que modifiquen agrupacions, exigim
# que el header `X-CSRF-Token` coincideixi amb el valor de la cookie
# `csrf_token`. Aquesta cookie es genera la primera vegada que un client
# fa qualsevol GET. El frontend la llegeix i la inclou a les peticions.
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
_CSRF_PROTECTED_PREFIXES = ("/api/agrupacions", "/api/admin")
_CSRF_EXEMPT_METHODS = {"GET", "HEAD", "OPTIONS"}


def _csrf_required(path: str, method: str) -> bool:
    if method in _CSRF_EXEMPT_METHODS:
        return False
    return any(path.startswith(p) for p in _CSRF_PROTECTED_PREFIXES)


@app.before_request
def _csrf_check():
    # Hook escapada per a tests existents que no envien CSRF token
    # (set explícitament app.config["CSRF_ENABLED"] = False per saltar el check).
    if app.config.get("CSRF_ENABLED", True) is False:
        return None
    if not _csrf_required(request.path, request.method):
        return None
    cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    header = request.headers.get(CSRF_HEADER_NAME, "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        log.warning("CSRF rebutjat path=%s method=%s ip=%s", request.path, request.method, request.remote_addr)
        return jsonify({"error": "CSRF token absent o invàlid"}), 403
    return None


@app.after_request
def _csrf_set_cookie(resp):
    if not request.cookies.get(CSRF_COOKIE_NAME):
        token = secrets.token_urlsafe(32)
        # Cookie llegible per JS (necessari per al double-submit); marcada
        # com SameSite=Strict per evitar enviament cross-site.
        resp.set_cookie(
            CSRF_COOKIE_NAME, token,
            samesite="Strict", httponly=False, secure=False, max_age=60 * 60 * 24 * 30,
        )
    return resp


# --- Rate-limit in-memory per IP -----------------------------------------
# Suficient per al cas d'ús actual (LAN, 2 workers Gunicorn). Cada worker
# té el seu propi comptador — acceptable perquè és defensiu, no estricte.
_rate_lock = Lock()
_rate_buckets: dict[str, deque] = defaultdict(deque)


def _rate_limit(key: str, max_req: int, window_sec: int) -> bool:
    """Retorna True si la petició està dins del límit, False si l'excedeix."""
    now = time.monotonic()
    cutoff = now - window_sec
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= max_req:
            return False
        bucket.append(now)
        return True


# --- Helpers d'errors estandarditzats ------------------------------------
# Definicions reals a `errors.py` (perquè es puguin importar des d'altres
# mòduls sense imports circulars amb `app.py`). Aquí mantenim els noms
# `_err_*` com a alias per no trencar les ~60 crides existents.
from errors import err_validacio as _err_validacio  # noqa: E402
from errors import err_db as _err_db  # noqa: E402
from errors import err_motor as _err_motor  # noqa: E402
from errors import err_generic as _err_genèric  # noqa: E402


# --- Autenticació: middleware + endpoints --------------------------------
# Si `AUTH_ENABLED=true` al .env, tots els endpoints excepte els llistats a
# `_AUTH_PUBLIC_PREFIXES` requereixen sessió. Per a `/api/*` retorna 401
# (JSON); per a la resta redirigeix a /login.
_AUTH_PUBLIC_PREFIXES = ("/login", "/logout", "/static", "/health", "/api/pbi", "/api/me", "/favicon.ico", "/calendari", "/api/carregues", "/api/carrega-detall")


@app.before_request
def _require_auth():
    if not auth.auth_enabled():
        return None
    path = request.path
    if any(path == p or path.startswith(p + "/") or path.startswith(p) for p in _AUTH_PUBLIC_PREFIXES):
        return None
    if session.get("user_id"):
        return None
    if path.startswith("/api/"):
        return jsonify({"error": "Autenticació requerida"}), 401
    return redirect(url_for("login", next=path))


@app.route("/login", methods=["GET", "POST"])
def login():
    next_path = request.values.get("next", "/") or "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    if request.method == "GET":
        return render_template("login.html", next_path=next_path)
    # POST: rate-limit per IP (max 5 intents/min)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    if "," in ip:
        ip = ip.split(",", 1)[0].strip()
    if not _rate_limit(f"login:{ip}", max_req=5, window_sec=60):
        return render_template("login.html", error="Massa intents. Espera un minut.", next_path=next_path), 429
    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    user = None
    try:
        user = auth.get_user_by_username(username)
    except Exception:
        log.exception("Login: error consultant usuari")
    if not user or not user.get("actiu") or not auth.verify_password(password, user["password_hash"]):
        try:
            import audit as _audit
            _audit.log("login_fallit", target=username or None, detall={"ip": ip})
        except Exception:
            pass
        return render_template("login.html", error="Credencials invàlides.", next_path=next_path), 401
    # Login OK
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["user_name"] = user["nom"]
    session["user_username"] = user["username"]
    session["user_rol"] = user["rol"]
    try:
        auth.actualitza_last_login(user["id"])
        import audit as _audit
        _audit.log("login_ok", target=user["username"])
    except Exception:
        pass
    return redirect(next_path)


@app.route("/logout", methods=["POST", "GET"])
def logout():
    if session.get("user_id"):
        try:
            import audit as _audit
            _audit.log("logout", target=session.get("user_username"))
        except Exception:
            pass
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/me")
def api_me():
    if not session.get("user_id"):
        return jsonify({"authenticated": False, "auth_enabled": auth.auth_enabled()})
    return jsonify({
        "authenticated": True,
        "auth_enabled": True,
        "username": session.get("user_username"),
        "nom": session.get("user_name"),
        "rol": session.get("user_rol"),
    })


# --- Admin: CRUD d'usuaris (rol admin) ---------------------------------
@app.route("/admin/usuaris")
@auth.requires_rol("admin")
def admin_usuaris_page():
    return render_template("admin_usuaris.html")


@app.route("/admin/overrides-data")
@auth.requires_rol("admin")
def admin_overrides_page():
    return render_template("admin_overrides.html")


@app.route("/api/admin/usuaris", methods=["GET"])
@auth.requires_rol("admin")
def api_admin_usuaris_llistar():
    try:
        items = auth.llistar_usuaris()
        # Format ISO de timestamps per al frontend
        for it in items:
            for k in ("created_at", "last_login_at"):
                if it.get(k) is not None:
                    it[k] = it[k].isoformat()
        return jsonify(items)
    except Exception:
        log.exception("admin_usuaris llistar")
        return _err_genèric()


@app.route("/api/admin/usuaris", methods=["POST"])
@auth.requires_rol("admin")
def api_admin_usuaris_crear():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip().lower()
    nom = (body.get("nom") or "").strip()
    rol = (body.get("rol") or "oficina").strip()
    password = body.get("password") or ""
    if not auth.es_email_valid(username):
        return _err_validacio("L'usuari ha de ser un email vàlid (p.ex. nom@agrienergia.com).")
    if not nom:
        return _err_validacio("El nom és obligatori.")
    if len(password) < 8:
        return _err_validacio("La contrasenya ha de tenir com a mínim 8 caràcters.")
    try:
        user = auth.crear_usuari(username, password, nom, rol)
        return jsonify({"id": user["id"], "username": user["username"], "rol": user["rol"]}), 201
    except ValueError as e:
        return _err_validacio(str(e))
    except Exception as e:
        # Captura UniqueViolation (independent del missatge en l'idioma del cluster PG)
        is_dup = False
        try:
            import psycopg.errors
            is_dup = isinstance(e, psycopg.errors.UniqueViolation) or \
                     isinstance(getattr(e, "__cause__", None), psycopg.errors.UniqueViolation)
        except Exception:
            pass
        if not is_dup:
            msg = str(e).lower()
            is_dup = any(s in msg for s in ("duplicate", "unique", "unicidad", "unicitat", "ja existeix"))
        if is_dup:
            return jsonify({"error": f"L'usuari '{username}' ja existeix."}), 409
        log.exception("admin_usuaris crear")
        return _err_genèric()


@app.route("/api/admin/usuaris/<int:id_>", methods=["PATCH"])
@auth.requires_rol("admin")
def api_admin_usuaris_actualitzar(id_):
    body = request.get_json(silent=True) or {}
    # No deixar que un admin es desactivi a si mateix (evita lockout)
    actiu = body.get("actiu")
    if actiu is False and session.get("user_id") == id_:
        return _err_validacio("No pots desactivar el teu propi compte.")
    try:
        user = auth.actualitzar_usuari(
            id_,
            nom=body.get("nom"),
            rol=body.get("rol"),
            actiu=actiu,
        )
        if not user:
            return jsonify({"error": "Usuari no trobat."}), 404
        return jsonify(user)
    except ValueError as e:
        return _err_validacio(str(e))
    except Exception:
        log.exception("admin_usuaris actualitzar")
        return _err_genèric()


@app.route("/api/admin/usuaris/<int:id_>/password", methods=["POST"])
@auth.requires_rol("admin")
def api_admin_usuaris_password(id_):
    body = request.get_json(silent=True) or {}
    nova = body.get("password") or ""
    try:
        if not auth.canvi_contrasenya(id_, nova):
            return jsonify({"error": "Usuari no trobat."}), 404
        return jsonify({"ok": True})
    except ValueError as e:
        return _err_validacio(str(e))
    except Exception:
        log.exception("admin_usuaris password")
        return _err_genèric()


# --- Admin: override de la data planificada de càrrega ---------------------
# KAIS sobreescriu car_fecsalida quan la càrrega passa a Sortida; el snapshot
# captura el valor pre-Sortida automàticament, però per a càrregues "perdudes"
# (ja en Sortida abans del deploy d'aquesta feature, o on el snapshot no
# arribava a temps) un admin pot definir manualment la data planificada.
def _parse_carrega_id(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    parts = s.split("/")
    if len(parts) != 3:
        return None
    eje, sca, car = parts
    if not (eje.isdigit() and len(eje) == 4):
        return None
    if not (sca.isdigit() and len(sca) == 2):
        return None
    if not car.isdigit():
        return None
    return f"{eje}/{sca}/{car.zfill(7)}"


@app.route("/api/admin/carrega-overrides", methods=["GET"])
@auth.requires_rol("admin")
def api_admin_overrides_llistar():
    try:
        import carrega_data_planificada as cdp
        return jsonify(cdp.llistar_overrides())
    except Exception:
        log.exception("admin overrides llistar")
        return _err_genèric()


@app.route("/api/admin/carrega-overrides", methods=["POST"])
@auth.requires_rol("admin")
def api_admin_overrides_crear_o_actualitzar():
    body = request.get_json(silent=True) or {}
    carrega_id = _parse_carrega_id(body.get("carrega_id", ""))
    if not carrega_id:
        return _err_validacio("carrega_id invàlid (format esperat: YYYY/SS/NNNNNNN).")
    dt_raw = (body.get("car_fecsalida") or "").strip()
    if not dt_raw:
        return _err_validacio("Cal indicar car_fecsalida (YYYY-MM-DD HH:MM).")
    # Accepta "YYYY-MM-DD" o "YYYY-MM-DD HH:MM"
    try:
        if len(dt_raw) <= 10:
            dt = datetime.strptime(dt_raw, "%Y-%m-%d")
        else:
            dt = datetime.strptime(dt_raw[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return _err_validacio("Format de data invàlid (YYYY-MM-DD o YYYY-MM-DD HH:MM).")
    motiu = (body.get("motiu") or "").strip() or None
    try:
        import carrega_data_planificada as cdp
        result = cdp.set_override(
            carrega_id=carrega_id,
            car_fecsalida=dt,
            motiu=motiu,
            created_by_id=session.get("user_id"),
        )
        audit.log("carrega_override_set", target=carrega_id,
                  detall={"car_fecsalida": dt.isoformat(), "motiu": motiu})
        return jsonify(result), 200
    except (ValueError, TypeError) as e:
        return _err_validacio(str(e))
    except Exception:
        log.exception("admin override set")
        return _err_genèric()


@app.route("/api/admin/carrega-overrides/<path:carrega_id>", methods=["DELETE"])
@auth.requires_rol("admin")
def api_admin_overrides_eliminar(carrega_id):
    cid = _parse_carrega_id(carrega_id)
    if not cid:
        return _err_validacio("carrega_id invàlid.")
    try:
        import carrega_data_planificada as cdp
        ok = cdp.delete_override(cid)
        if not ok:
            return jsonify({"error": "Override no trobat."}), 404
        audit.log("carrega_override_delete", target=cid)
        return jsonify({"ok": True})
    except Exception:
        log.exception("admin override delete")
        return _err_genèric()


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


@app.route("/")
def index():
    # Si l'usuari té rol 'magatzem', no té accés a la pàgina principal de
    # cerca/agrupació — el redirigim al seu inici natural (llista de
    # magatzem amb agrupacions pendents).
    if auth.auth_enabled() and session.get("user_rol") == "magatzem":
        return redirect(url_for("magatzem_llista"))
    avui = date.today()
    # Deep-link des de /calendari: ?desde=YYYY-MM-DD&fins=YYYY-MM-DD&focus=carrega_id
    desde_q = (request.args.get("desde") or "").strip()
    fins_q  = (request.args.get("fins")  or "").strip()
    focus_q = (request.args.get("focus") or "").strip()
    return render_template(
        "index.html",
        data_desde=desde_q or avui.isoformat(),
        data_fins=fins_q or (avui + timedelta(days=7)).isoformat(),
        focus_carrega=focus_q,
    )


@app.route("/calendari")
def calendari():
    return render_template("calendari.html")


@app.route("/magatzem", strict_slashes=False)
@auth.requires_rol("admin", "oficina", "magatzem")
def magatzem_llista():
    return render_template("magatzem_llista.html")


@app.route("/ajuda")
def ajuda():
    return render_template("ajuda.html")


@app.route("/control", strict_slashes=False)
@auth.requires_rol("admin", "oficina")
def control_llista():
    return render_template("control.html")


@app.route("/magatzem/<id_>")
@auth.requires_rol("admin", "oficina", "magatzem")
def magatzem_prep(id_):
    obj = agrupacions_store.obtenir(id_)
    if not obj:
        return render_template("magatzem_llista.html", error="Agrupació no trobada."), 404
    return render_template("magatzem_prep.html", agrupacio_id=id_, nom=obj.get("nom", ""))


@app.route("/api/transportistes")
@auth.requires_rol("admin", "oficina")
def api_transportistes():
    try:
        return jsonify(llistar_transportistes())
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a transportistes")
        return _err_db()
    except Exception:
        log.exception("transportistes")
        return _err_genèric()


@app.route("/api/carregues")
def api_carregues():
    rang, err = valida_rang_dates(request.args.get("desde"), request.args.get("fins"))
    if err:
        return _err_validacio(err)
    desde_d, fins_d = rang

    # Multi-transportista: accepta CSV o múltiples query params `tra_codi`
    tra_param = request.args.getlist("tra_codi")
    tra_codis: list[str] = []
    for raw in tra_param:
        for part in (raw or "").split(","):
            part = part.strip()
            if not part:
                continue
            v, err = valida_codi(part, "tra_codi", max_len=5)
            if err:
                return _err_validacio(err)
            tra_codis.append(v)

    estat_raw = request.args.get("estat")
    estat = None
    if estat_raw not in (None, ""):
        estat, err = valida_int(estat_raw, "estat", minim=0, maxim=99)
        if err:
            return _err_validacio(err)

    art_codi, err = valida_codi(request.args.get("art_codi"), "art_codi", max_len=20, obligatori=False)
    if err:
        return _err_validacio(err)

    limit, err = valida_int(request.args.get("limit", "500"), "limit", minim=1, maxim=1000)
    if err:
        return _err_validacio(err)
    offset, err = valida_int(request.args.get("offset", "0"), "offset", minim=0)
    if err:
        return _err_validacio(err)
    try:
        resp = llistar_carregues(
            desde_d.isoformat(), fins_d.isoformat(),
            tra_codis=tra_codis or None,
            estat=estat,
            art_codi=art_codi,
            limit=limit, offset=offset,
        )
        # Enriqueix cada càrrega amb les agrupacions desades on apareix.
        index = agrupacions_store.index_carregues_agrupades()
        for item in resp.get("items", []):
            item["agrupacions"] = index.get(item["carrega_id"], [])
        return jsonify(resp)
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a carregues")
        return _err_db()
    except Exception:
        log.exception("carregues")
        return _err_genèric()


@app.route("/api/estats-carregues")
@auth.requires_rol("admin", "oficina")
def api_estats_carregues():
    try:
        return jsonify(llistar_estats_carregues())
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a estats-carregues")
        return _err_db()
    except Exception:
        log.exception("estats-carregues")
        return _err_genèric()


@app.route("/api/articles")
@auth.requires_rol("admin", "oficina")
def api_articles():
    q, err = valida_codi(request.args.get("q"), "q", max_len=40, obligatori=False)
    # `valida_codi` rebutja espais; per a la cerca d'articles deixem accents/espais. Provem directament.
    q = (request.args.get("q") or "").strip()
    if len(q) > 40:
        return _err_validacio("'q' té un format invàlid.")
    try:
        return jsonify(cercar_articles(q))
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a articles")
        return _err_db()
    except Exception:
        log.exception("articles")
        return _err_genèric()


@app.route("/api/agrupacions", methods=["GET"])
@auth.requires_rol("admin", "oficina", "magatzem")
def api_agrupacions_llista():
    try:
        return jsonify(agrupacions_store.llistar())
    except Exception:
        log.exception("agrupacions llistar")
        return _err_genèric()


@app.route("/api/control/agrupacions", methods=["GET"])
@auth.requires_rol("admin", "oficina")
def api_control_agrupacions():
    origen = request.args.get("origen")
    if origen and origen not in ("desada", "impresa"):
        return _err_validacio("'origen' ha de ser 'desada' o 'impresa'.")
    try:
        return jsonify(agrupacions_store.llistar_control(origen=origen))
    except Exception:
        log.exception("control llistar")
        return _err_genèric()


@app.route("/api/agrupacions", methods=["POST"])
@auth.requires_rol("admin", "oficina")
def api_agrupacions_guardar():
    body = request.get_json(silent=True) or {}
    nom = (body.get("nom") or "").strip()
    if not nom:
        return _err_validacio("'nom' és obligatori.")
    if len(nom) > 80:
        return _err_validacio("'nom' té un format invàlid (màx 80 caràcters).")
    carregues, err = valida_llista_carregues(body.get("carregues"))
    if err:
        return _err_validacio(err)
    resultat = body.get("resultat")
    if not isinstance(resultat, dict):
        return _err_validacio("'resultat' és obligatori.")
    plantilla = bool(body.get("plantilla"))
    try:
        info = agrupacions_store.guardar(
            nom, carregues, resultat,
            plantilla=plantilla,
            created_by_id=session.get("user_id"),
        )
        log.info(
            "audit guardar agrupacio=%s nom=%s ip=%s n_carregues=%d plantilla=%s",
            info.get("id"), info.get("nom"), request.remote_addr, info.get("n_carregues", 0), plantilla,
        )
        return jsonify(info)
    except Exception:
        log.exception("agrupacions guardar")
        return _err_genèric()


@app.route("/api/agrupacions/imprimir", methods=["POST"])
@auth.requires_rol("admin", "oficina")
def api_agrupacions_imprimir():
    """Registra una impressió. Si `agrupacio_existent_id` ve i és vàlid (l'operari
    ja havia desat manualment), només deixa audit log sense duplicar. Si no,
    crea un registre nou a `agrupacions` amb `origen='impresa'` i nom auto.
    """
    body = request.get_json(silent=True) or {}
    existent_id = (body.get("agrupacio_existent_id") or "").strip() or None
    carregues, err = valida_llista_carregues(body.get("carregues"))
    if err:
        return _err_validacio(err)
    resultat = body.get("resultat")
    if not isinstance(resultat, dict):
        return _err_validacio("'resultat' és obligatori.")

    user_id = session.get("user_id")
    user_nom = (session.get("user_name") or "").strip()

    if existent_id:
        # Reimpressió d'una agrupació ja desada: només audit log
        try:
            audit.log(
                "agrupacio_impresa",
                target=existent_id,
                detall={
                    "n_carregues": len(carregues),
                    "reimpressio_sobre_desada": True,
                },
            )
            return jsonify({"id": existent_id, "creada": False})
        except Exception:
            log.exception("agrupacions imprimir (existent)")
            return _err_genèric()

    # Impressió fresh: crea registre nou amb origen='impresa'
    nom_auto = f"Imprès {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {user_nom}"[:80]
    try:
        info = agrupacions_store.guardar(
            nom_auto, carregues, resultat,
            plantilla=False,
            created_by_id=user_id,
            origen="impresa",
        )
        log.info(
            "audit imprimir agrupacio=%s nom=%s ip=%s n_carregues=%d",
            info.get("id"), info.get("nom"), request.remote_addr, info.get("n_carregues", 0),
        )
        return jsonify({**info, "creada": True})
    except Exception:
        log.exception("agrupacions imprimir (nova)")
        return _err_genèric()


@app.route("/api/plantilles", methods=["GET"])
@auth.requires_rol("admin", "oficina")
def api_plantilles_llista():
    try:
        return jsonify(agrupacions_store.llistar_plantilles())
    except Exception:
        log.exception("plantilles llistar")
        return _err_genèric()


@app.route("/api/agrupacions/<id_>", methods=["GET"])
@auth.requires_rol("admin", "oficina", "magatzem")
def api_agrupacions_obtenir(id_):
    obj = agrupacions_store.obtenir(id_)
    if not obj:
        return jsonify({"error": "Agrupació no trobada."}), 404
    return jsonify(obj)


@app.route("/api/agrupacions/<id_>", methods=["DELETE"])
@auth.requires_rol("admin", "oficina")
def api_agrupacions_eliminar(id_):
    if agrupacions_store.eliminar(id_):
        log.info("audit eliminar agrupacio=%s ip=%s", id_, request.remote_addr)
        return jsonify({"ok": True})
    return jsonify({"error": "Agrupació no trobada."}), 404


@app.route("/api/agrupacions/version")
def api_agrupacions_version():
    """Versió actual de l'índex d'agrupacions (per a polling lleuger des
    del frontend). El client compara aquest valor amb el que va veure
    l'última vegada i només refetcha la llista pesada si ha canviat."""
    return jsonify({"v": agrupacions_store.get_version()})


@app.route("/api/agrupacions/<id_>/producte", methods=["PATCH"])
@auth.requires_rol("admin", "oficina", "magatzem")
def api_agrupacions_producte(id_):
    body = request.get_json(silent=True) or {}
    art_codi, err = valida_codi(body.get("art_codi"), "art_codi", max_len=20)
    if err:
        return _err_validacio(err)
    preparat = bool(body.get("preparat"))
    obj = agrupacions_store.marca_producte(
        id_, art_codi, preparat,
        ip=request.remote_addr,
        marcat_per_id=session.get("user_id"),
    )
    if obj is None:
        return jsonify({"error": "Agrupació no trobada."}), 404
    log.info(
        "audit marca agrupacio=%s art=%s preparat=%s ip=%s",
        id_, art_codi, preparat, request.remote_addr,
    )
    return jsonify({"ok": True, "n_preparats": len(obj.get("productes_preparats") or [])})


@app.route("/api/agrupacions/<id_>/reset-preparats", methods=["POST"])
@auth.requires_rol("admin", "oficina", "magatzem")
def api_agrupacions_reset_preparats(id_):
    obj = agrupacions_store.reset_preparats(id_, ip=request.remote_addr)
    if obj is None:
        return jsonify({"error": "Agrupació no trobada."}), 404
    log.info("reset preparats agrupacio=%s ip=%s", id_, request.remote_addr)
    return jsonify({"ok": True, "n_preparats": 0})


@app.route("/api/agrupacions/<id_>/finalitzar", methods=["POST"])
@auth.requires_rol("admin", "oficina")
def api_agrupacions_finalitzar(id_):
    obj = agrupacions_store.marcar_finalitzada(
        id_, user_id=session.get("user_id"), ip=request.remote_addr,
    )
    if obj is None:
        return jsonify({"error": "Agrupació no trobada."}), 404
    log.info("audit finalitzar manual agrupacio=%s ip=%s", id_, request.remote_addr)
    return jsonify({"ok": True})


@app.route("/api/agrupacions/<id_>/reobrir", methods=["POST"])
@auth.requires_rol("admin", "oficina")
def api_agrupacions_reobrir(id_):
    obj = agrupacions_store.reobrir(
        id_, user_id=session.get("user_id"), ip=request.remote_addr,
    )
    if obj is None:
        return jsonify({"error": "Agrupació no trobada."}), 404
    log.info("audit reobrir agrupacio=%s ip=%s", id_, request.remote_addr)
    return jsonify({"ok": True})


@app.route("/api/carrega-detall")
def api_carrega_detall():
    eje, err = valida_codi(request.args.get("eje"), "eje", max_len=4)
    if err:
        return _err_validacio(err)
    sca, err = valida_codi(request.args.get("sca"), "sca", max_len=2)
    if err:
        return _err_validacio(err)
    car, err = valida_codi(request.args.get("car"), "car", max_len=7)
    if err:
        return _err_validacio(err)
    try:
        return jsonify(resum_carrega(eje, sca, car))
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a carrega-detall")
        return _err_db()
    except Exception:
        log.exception("carrega-detall")
        return _err_genèric()


@app.route("/api/agrupar", methods=["POST"])
@auth.requires_rol("admin", "oficina")
def api_agrupar():
    body = request.get_json(silent=True) or {}
    carregues, err = valida_llista_carregues(body.get("carregues"))
    if err:
        return _err_validacio(err)

    # Validació duplicats: una càrrega només pot estar en una agrupació.
    # Si ja és en qualsevol agrupació (activa o finalitzada), bloca amb 409.
    index = agrupacions_store.index_carregues_agrupades()
    duplicats = []
    for c in carregues:
        cid = c.get("carrega_id")
        existents = index.get(cid, [])
        if existents:
            duplicats.append({"carrega_id": cid, "agrupacions": existents})
    if duplicats:
        log.info("agrupar: bloquejat per duplicats — %d càrregues afectades", len(duplicats))
        return jsonify({
            "error": "Algunes càrregues ja són en una agrupació.",
            "duplicats": duplicats,
        }), 409

    try:
        log.info("agrupar: %d càrregues", len(carregues))
        resultat = agrupar(carregues)
        out = serialitzar(resultat)
        log.info(
            "audit agrupar ip=%s carregues=%d productes=%d palets=%d",
            request.remote_addr, len(carregues), len(out.get("productes", [])),
            out.get("total_palets_fisics", 0),
        )
        return jsonify(out)
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a agrupar")
        return _err_db()
    except ModuleNotFoundError:
        log.exception("App germana no disponible")
        return _err_motor()
    except Exception:
        log.exception("agrupar")
        return _err_genèric()


@app.route("/api/pbi/carregues")
def api_pbi_carregues():
    """Endpoint per a Power BI: una fila per càrrega, JSON pla, amb camps
    derivats (any/mes/setmana/dia) per facilitar el modelat.

    Autenticació: header `X-Api-Key` ha de coincidir amb la variable d'entorn
    `PBI_API_KEY`. Si no està configurada, l'endpoint retorna 503.

    Rang: ?desde=YYYY-MM-DD&fins=YYYY-MM-DD (per defecte: -90 dies a +60 dies).
    """
    api_key_esperada = os.environ.get("PBI_API_KEY", "").strip()
    if not api_key_esperada:
        return jsonify({"error": "PBI_API_KEY no configurada al .env"}), 503
    if not secrets.compare_digest(request.headers.get("X-Api-Key", ""), api_key_esperada):
        return jsonify({"error": "API key invàlida o absent"}), 401
    # Rate-limit defensiu: max 30 req/min per IP
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    if "," in ip:
        ip = ip.split(",", 1)[0].strip()
    if not _rate_limit(f"pbi:{ip}", max_req=30, window_sec=60):
        log.warning("Rate limit excedit a /api/pbi/carregues ip=%s", ip)
        return jsonify({"error": "Massa peticions; espera abans de reintentar"}), 429

    avui = date.today()
    desde_raw = request.args.get("desde") or (avui - timedelta(days=90)).isoformat()
    fins_raw = request.args.get("fins") or (avui + timedelta(days=60)).isoformat()
    rang, err = valida_rang_dates(desde_raw, fins_raw)
    if err:
        return _err_validacio(err)
    desde_d, fins_d = rang

    # Hard limit defensiu: no permetem dumps de més de 5000 files en una sola
    # petició, ni rangs de >730 dies. Si Power BI necessita anys d'historial,
    # ho ha de fer en peticions trossejades per any. Aquest cap evita timeouts
    # i pics de memòria al servidor.
    PBI_MAX_FILES = int(os.environ.get("PBI_MAX_FILES", "5000"))
    PBI_MAX_DIES = 730
    if (fins_d - desde_d).days > PBI_MAX_DIES:
        return _err_validacio(
            f"Rang massa ampli (max {PBI_MAX_DIES} dies). "
            f"Fes peticions trossejades per any."
        )

    # Paginació interna: llistar_carregues té un cap de 1000 per request,
    # però per a Power BI hem de retornar tot el rang sencer.
    items = []
    offset = 0
    PAS = 1000
    try:
        while True:
            resp = llistar_carregues_sql(
                desde_d.isoformat(), fins_d.isoformat(),
                limit=PAS, offset=offset,
            )
            batch = resp.get("items", [])
            items.extend(batch)
            total = resp.get("total", 0)
            offset += PAS
            if offset >= total or not batch:
                break
            if len(items) >= PBI_MAX_FILES:
                log.warning(
                    "pbi/carregues: rang massa gran (%d files), tallant a %d",
                    total, PBI_MAX_FILES,
                )
                items = items[:PBI_MAX_FILES]
                break
    except backend_dades.ERRORS_DADES:
        log.exception("DB error a pbi/carregues")
        return _err_db()
    except Exception:
        log.exception("pbi/carregues")
        return _err_genèric()

    DIES = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"]
    MESOS = ["Gener", "Febrer", "Març", "Abril", "Maig", "Juny",
             "Juliol", "Agost", "Setembre", "Octubre", "Novembre", "Desembre"]

    files = []
    for c in items:
        data_str = c.get("car_fecsalida") or c.get("car_fecha") or ""
        any_, mes, dia, setmana, dia_setmana_txt, mes_txt, any_mes, any_setmana = (
            None, None, None, None, "", "", "", ""
        )
        if data_str:
            try:
                yy, mm, dd = (int(x) for x in data_str.split("-"))
                from datetime import date as _date
                d = _date(yy, mm, dd)
                any_, mes, dia = yy, mm, dd
                iso_year, iso_week, iso_dow = d.isocalendar()
                setmana = iso_week
                dia_setmana_txt = DIES[iso_dow - 1]
                mes_txt = MESOS[mm - 1]
                any_mes = f"{yy:04d}-{mm:02d}"
                any_setmana = f"{iso_year:04d}-W{iso_week:02d}"
            except (ValueError, TypeError):
                pass
        files.append({
            "carrega_id": c.get("carrega_id"),
            "eje_ejercicio": c.get("eje_ejercicio"),
            "sca_serie": c.get("sca_serie"),
            "car_numero": c.get("car_numero"),
            "descripcio": c.get("car_descripcion") or "",
            "data_sortida": c.get("car_fecsalida"),
            "data_carrega": c.get("car_fecha"),
            "estat": c.get("car_estat"),
            "transportista_codi": c.get("tra_codi") or "",
            "transportista_nom": c.get("transportista") or "",
            "matricula": c.get("car_matricula") or "",
            "conductor": c.get("car_nomconductor") or "",
            "pes_net_real": c.get("car_pesonetocarga") or 0.0,
            "pes_teoric": c.get("car_pesoteorico") or 0.0,
            "kg_total": c.get("kg_total") or 0.0,
            "is_granel": bool(c.get("is_granel")),
            "palletitzable": bool(c.get("palletitzable")),
            "observacions": c.get("car_observaciones") or "",
            # Camps derivats per a Power BI
            "any": any_,
            "mes": mes,
            "dia": dia,
            "setmana": setmana,
            "any_mes": any_mes,
            "any_setmana": any_setmana,
            "dia_setmana": dia_setmana_txt,
            "mes_text": mes_txt,
        })
    return jsonify(files)


# Cache curta per a /health: comprovar SQL Server + PG + motor a cada
# request és costós (~500ms vist al log). Cachegem el resultat uns segons
# perquè el monitoring (que típicament fa poll cada 30s o més) no saturi
# els workers. TTL configurable per env HEALTH_CACHE_TTL_MS.
_HEALTH_CACHE = {"ts": 0.0, "body": None, "status": 200}
_HEALTH_LOCK = Lock()


def _calc_health():
    ok_db = ok_motor = ok_pg = False
    msg_db = msg_motor = msg_pg = ""
    try:
        conn = connectar()
        try:
            conn.execute("SELECT 1").fetchone()
            ok_db = True
        finally:
            conn.close()
    except Exception as e:
        msg_db = str(e)[:200]
    try:
        import db as _db
        ok_pg, msg_pg = _db.health_ok()
    except Exception as e:
        msg_pg = str(e)[:200]
    try:
        import motor  # noqa: F401
        ok_motor = hasattr(motor, "calcular_embalatges")
        if not ok_motor:
            msg_motor = "motor sense calcular_embalatges"
    except Exception as e:
        msg_motor = str(e)[:200]
    # Sonda del Service Layer: nomes si alguna funcio hi llegeix. Si cap no
    # l'usa, no val la pena pagar-ne el login. Quan s'usa, aquesta sonda fa
    # doble servei: comprova i mante la sessio calenta (el monitoring passa
    # cada 30 s i el login en fred costa ~2 s).
    ok_sl = None
    msg_sl = ""
    backends = backend_dades.backends_actius(FUNCIONS_DADES)
    if any(b == backend_dades.SL for b in backends.values()):
        try:
            from dades.sl.client import client as _sl_client
            ok_sl = _sl_client().viu()
            if backends.get("obtenir_descrip_articles") == backend_dades.SL                     or backends.get("cercar_articles") == backend_dades.SL:
                from dades.sl.carregues import escalfa as _sl_escalfa
                _sl_escalfa()
        except Exception as e:
            ok_sl = False
            msg_sl = str(e)[:200]

    tot_ok = ok_db and ok_motor and ok_pg and (ok_sl is not False)
    status = 200 if tot_ok else 503
    expose_detail = (os.environ.get("EXPOSE_HEALTH_DETAIL", "").strip().lower()
                     in ("1", "true", "yes"))
    body = {
        "ok": tot_ok,
        "db": {"ok": ok_db},
        "motor": {"ok": ok_motor},
        "pg": {"ok": ok_pg},
    }
    if ok_sl is not None:
        body["sl"] = {"ok": ok_sl}
    # Quin backend serveix cada funcio de dades. Davant d'una incidencia cal
    # poder saber si s'esta llegint per SQL o per Service Layer sense haver
    # d'entrar al servidor a mirar el .env.
    body["backends"] = backends
    fallbacks = backend_dades.comptador_fallbacks()
    if fallbacks:
        # Si el fallback a SQL salta, ha de ser visible: sense aixo un backend
        # SL que falli sovint sembla que funcioni perfectament.
        body["fallbacks_sql"] = fallbacks
    if expose_detail:
        body["db"]["msg"] = msg_db
        body["motor"]["msg"] = msg_motor
        body["pg"]["msg"] = msg_pg
        if ok_sl is not None:
            body["sl"]["msg"] = msg_sl
    return body, status


@app.route("/health")
def health():
    try:
        ttl_ms = int(os.environ.get("HEALTH_CACHE_TTL_MS", "5000"))
    except ValueError:
        ttl_ms = 5000
    now = time.monotonic()
    with _HEALTH_LOCK:
        cached_ts = _HEALTH_CACHE["ts"]
        cached_body = _HEALTH_CACHE["body"]
        cached_status = _HEALTH_CACHE["status"]
    if cached_body is not None and (now - cached_ts) * 1000 < ttl_ms:
        return jsonify(cached_body), cached_status
    body, status = _calc_health()
    with _HEALTH_LOCK:
        _HEALTH_CACHE["ts"] = now
        _HEALTH_CACHE["body"] = body
        _HEALTH_CACHE["status"] = status
    return jsonify(body), status


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5004")), debug=False)
