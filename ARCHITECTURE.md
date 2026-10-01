# Arquitectura

## Visió general

Aplicació Flask que combina dues fonts de dades:

- **SAP B1** (lectura) per dues vies commutables: **Service Layer** (OData v3, el camí suportat per SAP) i **SQL Server directe** amb `pyodbc` i `ApplicationIntent=ReadOnly` (el d'abans, que es manté com a xarxa de seguretat). Taules i UDT: `@SEI_ORDENCARGA`, `@SEITRANSPORTEF`, `ORDR`, `RDR1`, `OITM`, `OCRD`, `CRD1`.
- **PostgreSQL** (lectura/escriptura, via `psycopg` + pool) — persistència local: agrupacions desades, productes preparats, usuaris, audit log.

El càlcul d'embalatges es delega a una app germana (`preparacioComandesVenda`) carregada via `sys.path` (`agregador.py` → `motor.calcular_embalatges`).

```
┌──────────────────────┐     ┌────────────────────┐     ┌────────────────┐
│  Oficina             │     │  Tablet (magatzem) │     │  Power BI      │
│  /  · /calendari     │     │  /magatzem/<id>    │     │  /api/pbi/*    │
└──────────┬───────────┘     └────────┬───────────┘     └──────┬─────────┘
           │                          │                         │
           ▼                          ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Flask (app.py)                                                         │
│  ├─ valida.py        validació inputs                                   │
│  ├─ auth.py          sessions, hash PBKDF2, decoradors @requires_rol    │
│  ├─ audit.py         registre d'accions a audit_logs                    │
│  ├─ CSRF middleware  double-submit cookie a PATCH/POST/DELETE           │
│  ├─ Rate-limit       /api/pbi 30/min, /login 5/min per IP               │
│  ├─ Headers seguretat (CSP 'self', X-Frame-Options, …)                  │
│  └─ Logging rotat                                                       │
└──────┬──────────────────────────┬──────────────────────┬────────────────┘
       │                          │                      │
       ▼                          ▼                      ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌────────────────┐
│ consultes_carregues  │  │ agregador.py         │  │ agrupacions_   │
│ (façana)             │  │  ↓ (sys.path)        │  │ store.py       │
│   ↓ dades/backend.py │  │ motor.calcular_      │  │ • CRUD         │
│   SAP_BACKEND=sql|sl │  │   embalatges()       │  │ • cache index  │
│                      │  │ (app germana, SQL)   │  │ • get_version  │
└──────┬────────┬──────┘  └──────┬───────────────┘  └──────┬─────────┘
       │        │                │ pyodbc                  │ psycopg
       │ pyodbc │ HTTPS          ▼                         ▼
       ▼        ▼         ┌──────────────┐  ┌──────────────────────────┐
┌─────────────┐ ┌───────┐ │ SQL Server   │  │ PostgreSQL                │
│ SQL Server  │ │Service│ │ (motor)      │  │ • agrupacions            │
│ (ReadOnly)  │ │Layer  │ └──────────────┘  │ • productes_preparats    │
│ @SEI_ORDEN- │ │OData  │                   │ • agrupacio_carregues    │
│  CARGA ·    │ │v3     │                   │ • v_agrupacions_estat    │
│ ORDR · RDR1 │ │       │                   │ • usuaris (auth)         │
│ OITM · OCRD │ │       │                   │ • audit_logs             │
│ CRD1        │ │       │                   │ • ordre_carrega_cache ───┼── agregats
└─────────────┘ └───────┘                   │ • agregats_meta          │   del llistat
                                            └──────────────────────────┘
```

## Components

### Backend

- **`app.py`** — Punt d'entrada Flask, ~800 línies.
  - Carrega `.env` local i `PREPARACIO_PATH/.env` (en aquest ordre).
  - Injecta `PREPARACIO_PATH` a `sys.path` perquè `agregador.py` pugui importar `motor` i `models`.
  - Configura `RotatingFileHandler` (2MB × 5).
  - Middlewares `@app.before_request`/`@app.after_request`: headers de seguretat (CSP, X-Frame, Referrer-Policy), CSRF check + cookie, autenticació quan `AUTH_ENABLED=true`.
  - Decoradors per rol als endpoints concrets (`@auth.requires_rol("admin", "oficina")`).
  - Errors gestionats: `backend_dades.ERRORS_DADES` (`pyodbc.Error` + `SLError`) → 503, `ModuleNotFoundError` → 503, resta → 500. Missatges interns només al log; `/health` retorna només booleans en producció (`EXPOSE_HEALTH_DETAIL=false`).

- **`valida.py`** — Validadors purs (sense efectes laterals). Cada funció retorna `(valor, err)`.

- **`consultes_carregues.py`** — Façana. Manté la superfície d'import de sempre
  (`app.py` i `agregador.py` no la coneixen de cap altra manera) i despatxa cada
  funció al backend que digui el `.env`. La implementació real viu a `dades/`:

  - **`dades/sql/carregues.py`** — SQL Server directe amb `pyodbc`, la de sempre.
    Una connexió per crida, tancada al `finally`. SQL pesat (subconsultes
    correlacionades) per a `kg_total`, `num_comandes`, `is_granel` i `palletitzable`.
  - **`dades/sl/`** — Service Layer. `client.py` (capa de lectura OData sobre
    l'`SLClient` de l'app germana), `odata.py` (literals i filtres),
    `cache_articles.py` (mestre d'articles en memòria) i `carregues.py` (les set
    funcions).
  - **`dades/backend.py`** — El commutador: `SAP_BACKEND`,
    `SAP_BACKEND_<FUNCIO>`, `SAP_BACKEND_FALLBACK`, i `ERRORS_DADES` (la tupla
    d'excepcions dels dos backends, perquè `SLError` no hereta de `pyodbc.Error`).
  - **`dades/agregats.py`** — Els quatre camps derivats del llistat, precalculats
    a PostgreSQL. El Service Layer no els pot calcular: no agrega ni filtra sobre
    línies de document, i les línies no es poden retallar amb `$select`. Els
    refresca `scripts/refrescar_agregats.py` per timer, i això fa que el llistat
    sigui **eventualment consistent** (la fitxa de detall segueix en viu).

  Per què existeix la migració: SAP no suporta llegir les seves taules per SQL
  directe. `scripts/paritat_backends.py` compara els dos backends i és la porta
  abans de commutar-ne cap.

- **`agregador.py`** — Per cada càrrega seleccionada:
  1. Llegeix les comandes (Detcargas amb `det_tipo IN ('A','P')`).
  2. Per cada comanda crida `motor.calcular_embalatges(sal, cpa)` de l'app germana — l'import és diferit i cau a `ModuleNotFoundError → 503` si l'app germana no és disponible.
  3. Acumula: `{producte → {càrrega → palets}}` + `{tipus_palet → {càrrega → quantitat}}`.
  4. Serialitza a JSON pla per al frontend.

- **`agrupacions_store.py`** — CRUD a PostgreSQL.
  - `guardar` / `obtenir` / `eliminar` / `llistar` / `llistar_plantilles`.
  - `marca_producte`, `reset_preparats` (productes preparats per magatzem).
  - `index_carregues_agrupades()` amb cache local per worker: retorna `{carrega_id → [agrupacions]}`. El cache es valida contra el comptador global a la taula `meta_agrupacions` de PostgreSQL — així workers Gunicorn diferents detecten les escriptures fets pels altres sense compartir memòria.
  - `get_version()`: llegeix el comptador global de la BD. Cada escriptura el bumpa atòmicament dins la mateixa transacció (`_bump_version(cur)`). El frontend en fa polling lleuger per detectar canvis en temps real.

- **`auth.py`** — Autenticació amb usuaris locals.
  - Hash: `pbkdf2_sha256$<iter>$<salt>$<hash>` (200k iter, sense dependències externes). Format extensible a Argon2/scrypt al futur.
  - CRUD d'usuaris: `crear_usuari`, `llistar_usuaris`, `obtenir_usuari`, `actualitzar_usuari`, `canvi_contrasenya`.
  - Decoradors: `@requires_auth`, `@requires_rol("admin", ...)`.
  - Sessió via Flask `session` (cookie signada amb `app.secret_key`).
  - Activat per `AUTH_ENABLED=true` al `.env`. Si està desactivat, els decoradors passen sense fer res (mode dev).

- **`audit.py`** — Registre d'accions importants a `audit_logs`.
  - `audit.log(accio, target=None, detall=None)` — tolerant a errors (warning si falla, mai bloqueja l'acció principal).
  - Captura automàticament IP, `user_id`, `user_name` de la sessió Flask actual.
  - Instrumentat a: desar/eliminar agrupació, marcar/desmarcar producte, reset preparats, login OK/fallit, logout, crear/actualitzar usuari, password reset.

- **`db.py`** — Pool de connexions PostgreSQL (`psycopg_pool.ConnectionPool`, min=1/max=5 per defecte). Context manager `get_conn()` per a transaccions.

### Frontend

Vanilla JS sense framework. Tres "modes":

- **Oficina (`/`, `templates/index.html`, `static/js/app.js`)** — ~2500 línies:
  - Estat `state` global dins una IIFE.
  - Re-render diff per `carrega_id` a la taula de càrregues per evitar reconstruir el `<tbody>`.
  - Event delegation al `<tbody>`: un sol listener despatxa per `data-role`.
  - Component `crearMultiSelect(...)` reutilitzable (chips + dropdown cercable + teclat).
  - Modal de resultat (`<dialog>`) amb impressió personalitzada: cada palet `N×M` colorit pel transportista.
  - **Polling lleuger** d'`/api/agrupacions/version` cada 5s — si la versió canvia, re-fetcheja `/api/carregues` amb els filtres actuals i re-renderitza silenciosament (preservant selecció/filtre/scroll). Pausat quan la pestanya és al fons o un dialog és obert.
  - `fetchJson()` injecta automàticament el header `X-CSRF-Token` a `PATCH/POST/DELETE`.
  - Cache local de detalls expandits (`detallCache` Map).

- **Calendari (`/calendari`, `static/js/calendari.js`)**:
  - Vista mensual amb columnes Dl-Dv; events de cap de setmana a una secció inferior.
  - KPI cards (càrregues, kg total, setmana actual, granel del mes).
  - Color per transportista (paleta fixa de 10 colors per ordre de freqüència) a la tira esquerra i dreta de cada event.
  - Granel: variant teal + pastilla "GRA".
  - Picker mes/any clicable al títol; auto-refresh cada 10 min.
  - Tooltip flotant amb fletxa i auto-flip; legenda clicable per filtrar per transportista.

- **Magatzem (`/magatzem`, `/magatzem/<id>`, `static/js/magatzem.js`)**:
  - Vista llista d'agrupacions desades (URL pròpia per fer-la usable des de la tablet del magatzem).
  - Vista preparació (`/magatzem/<id>`): cards grans amb checkbox "Preparat" de 64×64.
  - Polling cada 5s mentre la pestanya és visible per reflectir canvis fets des d'altres dispositius.
  - Pintat optimista al togglar: aplica immediatament a la UI i fa rollback si el `PATCH` falla.
  - `fetchJ()` injecta automàticament `X-CSRF-Token`.

- **Administració (`/admin/usuaris`, `static/js/admin_usuaris.js`)** — només rol `admin`:
  - Taula d'usuaris amb 3 accions per fila (editar nom/rol/actiu, canvi de contrasenya, desactivar/activar).
  - Modals `<dialog>` per crear/editar i per resetejar contrasenya.

- **Login (`/login`, `templates/login.html`)**:
  - Pàgina autònoma (sense IIFE, només form HTML).
  - Rate limit per IP (5 intents/min).

- **`static/js/fmt.js`** — `fmtData` i `fmtDataHora` exportats com a globals i com a CommonJS perquè `tests/test_format.mjs` els pugui importar des de Node sense duplicar codi.

## Endpoints

| Mètode | Path | Rols | Notes |
|---|---|---|---|
| `GET` | `/` | admin, oficina | (magatzem → redirigit a `/magatzem`) |
| `GET` | `/calendari` | tots auth | |
| `GET` | `/magatzem`, `/magatzem/<id>` | tots auth | |
| `GET` | `/ajuda` | tots auth | |
| `GET/POST` | `/login`, `/logout` | públic | rate-limit 5/min/IP |
| `GET` | `/admin/usuaris` | admin | |
| `GET/POST/PATCH` | `/api/admin/usuaris*` | admin | CSRF protegit |
| `GET` | `/api/carregues`, `/api/transportistes`, `/api/articles`, `/api/estats-carregues`, `/api/carrega-detall` | admin, oficina | |
| `POST` | `/api/agrupar` | admin, oficina | |
| `GET` | `/api/agrupacions` (llistat) | tots auth | |
| `POST` | `/api/agrupacions` (desar) | admin, oficina | CSRF |
| `GET` | `/api/agrupacions/<id>` | tots auth | |
| `DELETE` | `/api/agrupacions/<id>` | admin, oficina | CSRF |
| `PATCH` | `/api/agrupacions/<id>/producte` | tots auth | CSRF |
| `POST` | `/api/agrupacions/<id>/reset-preparats` | tots auth | CSRF |
| `GET` | `/api/agrupacions/version` | tots auth | polling lleuger |
| `GET` | `/api/plantilles` | admin, oficina | |
| `GET` | `/api/pbi/carregues` | header `X-Api-Key` | rate-limit 30/min/IP |
| `GET` | `/api/me` | tots auth | |
| `GET` | `/health` | públic | només booleans en producció |

## Decisions de disseny clau

- **No hi ha framework JS** — l'app és prou petita per mantenir-se vanilla; afegir React/Vue introduiria build pipeline i complexitat injustificada.
- **El motor d'embalatges no es duplica** — depenem de l'app germana via `sys.path`. El cost és l'acoblament; el benefici és no replicar la lògica d'embalatges.
- **Sense dependències addicionals per seguretat** — hash amb `hashlib.pbkdf2_hmac` (built-in), CSRF i rate-limit manuals amb dict in-memory, sessions amb Flask. Trade-off: rate-limit no es comparteix entre workers Gunicorn (acceptable perquè és defensiu, no estricte).
- **Persistència a PostgreSQL local** (migrat des de JSON el 2026-06-12) — permet vistes, índexs, audit log relacional i FKs amb `ON DELETE CASCADE`. Tot el cluster es comparteix amb les apps germanes al servidor de Lab FC.
- **Estat "preparat" al servidor** — els canvis des de la tablet són immediatament visibles per oficina (i viceversa) amb polling 5s. Sense WebSockets perquè no cal la latència sub-segon i un SSE per worker satura Gunicorn ràpid.
- **Una càrrega només pot estar en una agrupació** (bloqueig dur) — política de producte, no decisió tècnica. Política aplicada al backend (`POST /api/agrupar` rebutja si troba duplicats) i visible al frontend (badge a la fila bloqueja el checkbox).
- **CSP estricta** (`script-src 'self'`) — cap script inline; els valors dinàmics passen via `data-*` attributes al `<body>`.

## Errors i robustesa

- Validació estricta a tots els endpoints — qualsevol input deformat retorna 400 amb un missatge clar abans de tocar SQL.
- Errors de dades de SAP (SQL Server o Service Layer) retornen 503 "Error de connexió amb la base de dades"; el detall queda al log.
- Si el llistat va per Service Layer, `/health` vigila l'antiguitat dels agregats i retorna 503 si se passa d'`AGREGATS_MAX_ANTIGUITAT_S`: un refrescador encallat en silenci serviria dades velles sense avisar.
- Si `motor.py` no es pot importar, l'agrupació retorna 503 "Motor no disponible".
- Si `audit.log()` falla (PG caigut, taula absent), només `log.warning` — l'acció principal mai falla per culpa de l'audit.
- La cache d'`index_carregues_agrupades` es valida contra el comptador global de versió a la taula `meta_agrupacions` (BD), així que workers Gunicorn diferents detecten les escriptures dels altres a la propera lectura.
- El frontend mostra toasts al carregar si `/health` informa que alguna dependència està KO.

## Tests

- `tests/test_validacions.py` cobreix tot `valida.py` (28 casos).
- `tests/test_agrupacions_store.py` — proves del CRUD PG (auto-skip si `PG_HOST` no està configurat).
- `tests/test_endpoints.py` — smoke test dels endpoints principals.
- `tests/test_agregador.py` — proves de l'agregador.
- `tests/test_format.mjs` cobreix els helpers de format JS (14 casos, Node).
- **Coverage gaps reconeguts**: polling real-time, endpoint PBI, calendari, auth/CSRF (taller pendent).

## Coses fora d'abast

- Integració AD/LDAP (auth és amb usuaris locals a PG; queda obert si en algun moment cal SSO).
- WebSockets / SSE per al refresc real-time (polling 5s és suficient i molt més robust amb Gunicorn).
- Internacionalització — només català.
- Multi-empresa / multi-magatzem.
- Generació de PDF al backend (la impressió la fa el navegador via `@media print`).
- HTTPS (avui només LAN; si en algun moment cal Internet, Apache afegeix TLS sense canvis a l'app).
