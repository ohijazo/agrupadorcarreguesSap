# Manual tècnic — Agrupació de Càrregues

**Última revisió:** 2026-06-19
**Responsable:** Oscar Hijazo (ohijazo@agrienergia.com)
**Repositori:** https://github.com/ohijazo/Agrupador-de-Carregues
**Servidor:** `ae01farwebsrv.agrienergia.local` (192.168.11.244) — `/var/www/agrupacio-carregues`

---

## 1. Descripció funcional

L'aplicació **Agrupació de Càrregues** automatitza la consolidació d'embalatges de múltiples càrregues de transport en un únic resum per producte, i guia el preparador del magatzem amb una checklist tàctil.

**Procés que cobreix:**

1. **Oficina** entra a la pàgina principal, filtra càrregues per data, transportista, estat o article.
2. Selecciona un conjunt de càrregues que sortiran el mateix dia i prem **Agrupar**.
3. L'app crida el motor d'embalatges, calcula palets per producte i transport i mostra el resultat.
4. L'oficina **desa** l'agrupació amb un nom descriptiu (per ex. "Sortida 2026-06-22 matí").
5. **Magatzem** obre la tablet a `http://<servidor>:5002/magatzem`, tria l'agrupació desada i veu cards grans amb cada article i la quantitat de sacs.
6. A mesura que prepara els palets, **marca** cada producte com a "Preparat". L'estat queda visible en temps real a oficina.
7. Quan acaba, l'agrupació queda **Acabada** (verda) o pot tancar-se manualment des de la pantalla `/control` (taronja "Tancada").

**Usuaris (3 rols):**

- `admin` — administra usuaris, accés a totes les funcions, /control i /admin/usuaris.
- `oficina` — fa agrupacions, les desa, veu /control, no pot crear usuaris.
- `magatzem` — només la checklist de magatzem (no veu càrregues primàries ni /control).

**Pàgines clau:**

- `/` — pàgina principal (oficina). Filtres, llistat, agrupació, impressió.
- `/calendari` — vista mensual de càrregues per data, amb colors per transportista.
- `/magatzem` — llistat d'agrupacions desades pendents (vista tàctil).
- `/magatzem/<id>` — checklist d'una agrupació concreta.
- `/control` — seguiment global d'estat (admin/oficina): qui ha preparat què i quan.
- `/admin/usuaris` — gestió d'usuaris (admin).
- `/ajuda` — manual d'usuari per als operaris.

---

## 2. Arquitectura tècnica

**Stack:**

- **Backend:** Python 3.10+ amb Flask 3.x (sense ORM; queries SQL directes).
- **Frontend:** Vanilla JavaScript (sense framework), HTML/CSS estàtics. Cap build pipeline.
- **Bases de dades:** PostgreSQL 17 (estat propi) + SQL Server (ERP, només lectura via `pyodbc` + `ApplicationIntent=ReadOnly`).
- **Servidor web (prod):** Gunicorn darrere d'Apache, amb el servei `agrupacio-carregues.service` (systemd).
- **Servidor (local dev):** Flask dev server al port 5003.

**Diagrama (flux principal):**

```
Clients (oficina / magatzem / PowerBI)
    |
    v   HTTPS
Apache  ->  Gunicorn  ->  Flask (app.py)
                            |
                            +-> PostgreSQL local
                            |     agrupacions, productes_preparats,
                            |     usuaris, audit_logs
                            |
                            +-> SQL Server ERP (lectura)
                            |     Cargas, Detcargas, ALBLINIA, TRANS
                            |
                            +-> motor.calcular_embalatges()
                                  (via sys.path -> PreparacioComandesVenda)
```

**Dependències Python principals** (vegeu `requirements.txt`):

| Paquet | Per a què |
|---|---|
| `Flask==3.1.3` | Framework web |
| `pyodbc==5.3.0` | Connexió a SQL Server (ERP) |
| `psycopg[binary]==3.3.4` | Connexió a PostgreSQL |
| `psycopg-pool==3.3.1` | Pool de connexions PG |

**Acoblament amb l'app germana:** `agregador.py` importa `motor.calcular_embalatges` de `P:\PreparacioComandesVenda` via `sys.path`. Sense aquesta app, l'agrupació retorna 503.

**Fitxers clau:**

- `app.py` — Punt d'entrada Flask, rutes, middleware (auth, CSRF, headers, rate-limit).
- `consultes_carregues.py` — Queries SQL Server (càrregues, comandes, articles).
- `agregador.py` — Orquestra el motor per produir l'agrupació.
- `agrupacions_store.py` — CRUD a PostgreSQL de les agrupacions desades.
- `auth.py` — Autenticació local (pbkdf2_sha256, sessions Flask).
- `audit.py` — Registre d'accions a la taula `audit_logs`.
- `db.py` — Pool de connexions PostgreSQL.
- `db/schema.sql` — Esquema complet de PG (per a noves instal·lacions).
- `db/migrations/` — Migracions idempotents per a BD ja en marxa.

---

## 3. Configuració i desplegament

### 3.1 Variables d'entorn (`.env`)

Es llegeix `./.env` local primer, després `PREPARACIO_PATH/.env` com a fallback per a credencials SQL Server compartides amb l'app germana.

```ini
# SQL Server (ERP, només lectura) — sol venir de l'app germana
SQL_SERVER=servidor\instancia
SQL_DATABASE=GWSV_AGRI
SQL_USER=usuari
SQL_PASSWORD=secret
PREPARACIO_PATH=/var/www/preparacio-comandes-venda

# PostgreSQL (estat propi)
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=agrupaciocarregues
PG_USER=app_agrupacions
PG_PASSWORD=...
PG_POOL_MIN=1
PG_POOL_MAX=5

# Autenticació
AUTH_ENABLED=true                # false només per dev local
SECRET_KEY=...                   # generar amb secrets.token_hex(32)

# Power BI (opcional)
PBI_API_KEY=...                  # header X-Api-Key requerit

# Producció
EXPOSE_HEALTH_DETAIL=false       # true només per dev
```

### 3.2 Desplegament inicial (servidor nou)

```bash
# 1. Clonar
sudo -u www-data git clone https://github.com/ohijazo/Agrupador-de-Carregues.git \
    /var/www/agrupacio-carregues
cd /var/www/agrupacio-carregues

# 2. Instal·lar dependències
sudo -u www-data python3 -m venv venv
sudo -u www-data ./venv/bin/pip install -r requirements.txt

# 3. Crear BD PostgreSQL (com a superuser de PG):
sudo -u postgres psql -c "CREATE DATABASE agrupaciocarregues;"
sudo -u postgres psql -c "CREATE USER app_agrupacions WITH PASSWORD '...';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE agrupaciocarregues TO app_agrupacions;"

# 4. Carregar esquema (com a superuser per crear taules/vistes):
sudo -u postgres psql -d agrupaciocarregues -f db/schema.sql

# 5. Crear .env amb valors reals (chmod 640, owner www-data)

# 6. Servei systemd (vegeu /etc/systemd/system/agrupacio-carregues.service)
sudo systemctl daemon-reload
sudo systemctl enable agrupacio-carregues.service
sudo systemctl start agrupacio-carregues.service
```

### 3.3 Desplegament d'una actualització rutinària

```bash
# 1. Pull del codi
sudo -u www-data git -C /var/www/agrupacio-carregues pull

# 2. Si hi ha migracions noves, aplicar-les com a superuser de PG:
sudo -u www-data bash -c '
  set -a && source /var/www/agrupacio-carregues/.env && set +a
  PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U postgres -d "$PG_DATABASE" \
      -f /var/www/agrupacio-carregues/db/migrations/00X_nova.sql
'

# 3. Reiniciar el servei
sudo systemctl restart agrupacio-carregues.service
sudo systemctl status agrupacio-carregues.service --no-pager
```

> Les migracions són **idempotents** (`IF NOT EXISTS` / `DO $$ ... EXCEPTION` blocks) — es poden tornar a executar sense risc.

### 3.4 Entorns

| Entorn | URL | Servidor | Port | BD | Notes |
|---|---|---|---|---|---|
| Local (dev) | http://127.0.0.1:5003 | Portàtil | 5003 | `agrupaciocarregues_dev` (local) | `python app.py`, no Gunicorn |
| Producció | http://ae01farwebsrv.agrienergia.local/ (192.168.11.244) | `ae01farwebsrv.agrienergia.local` | Gunicorn rere Apache | `agrupaciocarregues` | systemd, www-data |

---

## 4. Accessos i permisos

### 4.1 Usuari del sistema operatiu (servidor)

L'app corre com a `www-data`. Tots els fitxers han d'estar com a `chown www-data:www-data` i `.env` com a `chmod 640`.

### 4.2 Rols d'aplicació

| Rol | Pot fer | NO pot fer |
|---|---|---|
| `admin` | Tot, inclou `/admin/usuaris` i `/control` | — |
| `oficina` | Crear/editar agrupacions, /control, imprimir | Crear usuaris |
| `magatzem` | Marcar productes preparats al checklist | Veure càrregues primàries, /control |

### 4.3 Crear/modificar usuaris

- **Via UI:** Login com a `admin` → `/admin/usuaris` → "Nou usuari" o editar.
- **Via Python (reset de contrasenya per emergència):**
  ```bash
  cd /var/www/agrupacio-carregues
  sudo -u www-data ./venv/bin/python -c "
  import os
  for l in open('.env'):
      l=l.strip()
      if l and '=' in l and not l.startswith('#'):
          k,v=l.split('=',1); os.environ[k.strip()]=v.strip()
  import auth
  print(auth.canvi_contrasenya(<USER_ID>, 'nova_temporal'))
  "
  ```

### 4.4 Hash de contrasenyes

Format: `pbkdf2_sha256$200000$<salt_b64>$<hash_b64>` (built-in Python, sense dependències externes). Migrable a Argon2 en el futur.

### 4.5 Accessos a BD

- **PostgreSQL `app_agrupacions`**: usuari de l'app, ALL PRIVILEGES sobre la BD pròpia. NO té rights per a `ALTER TABLE` sobre taules creades per `postgres` (per això les migracions van amb `postgres`).
- **PostgreSQL `postgres`** (superuser): només per a migracions i debug.
- **SQL Server**: només lectura. Compartida amb `PreparacioComandesVenda`.

---

## 5. Base de dades

### 5.1 PostgreSQL (estat propi)

Motor: PostgreSQL 12+ (testat amb 17). 6 taules + 1 vista.

| Taula | Propòsit | Camps clau |
|---|---|---|
| `agrupacions` | Capçalera d'una agrupació desada | `id` (UUID), `nom`, `ts`, `carregues` (JSONB), `resultat` (JSONB), `created_by_id`, `finalitzada_manual_at`, `finalitzada_manual_per_id` |
| `productes_preparats` | Quin producte ha marcat l'operari de magatzem | `agrupacio_id`, `art_codi`, `marcat_ts`, `marcat_per_id`, `marcat_ip` |
| `agrupacio_carregues` | Índex desnormalitzat carrega → agrupacions (per a "una càrrega = una agrupació") | `carrega_id`, `agrupacio_id` |
| `meta_agrupacions` | Comptador global de versió per a invalidar cache entre workers | `id`, `version` |
| `usuaris` | Auth local | `id`, `username` (email), `password_hash`, `nom`, `rol`, `actiu` |
| `audit_logs` | Registre d'accions importants | `ts`, `user_id`, `user_name`, `ip`, `accio`, `target`, `detall` (JSONB) |

**Vista `v_agrupacions_estat`**: deriva `finalitzada = (manual_at NOT NULL) OR (n_preparats >= n_productes)`.

**Relacions clau:**

- `agrupacions.created_by_id → usuaris.id` (ON DELETE SET NULL)
- `productes_preparats.agrupacio_id → agrupacions.id` (ON DELETE CASCADE)
- `productes_preparats.marcat_per_id → usuaris.id` (ON DELETE SET NULL)
- `agrupacio_carregues.agrupacio_id → agrupacions.id` (ON DELETE CASCADE)

### 5.2 Migracions

Ubicació: `db/migrations/00X_nom.sql`. Cada migració és **idempotent** (es pot reaplicar sense canvi).

Migracions actuals:
- `002_user_tracking.sql` — Afegeix `created_by_id` i `marcat_per_id`.
- `003_finalitzacio_manual.sql` — Afegeix `finalitzada_manual_at` i actualitza vista.

Per aplicar una migració, vegeu **§ 3.3**.

### 5.3 SQL Server (ERP, lectura)

Taules consultades (mai modificades):

| Taula | Per a què |
|---|---|
| `Cargas` | Capçalera de càrregues (fecsalida, fecllegada, transportista, observacions) |
| `Detcargas` | Línies de càrrega (relació amb comandes via det_documento) |
| `ALBLINIA` | Línies d'albarà (kg per article) |
| `ARTICLES` | Mestre d'articles (descripció, unitat) |
| `CPALBARA` | Capçalera d'albarans (per resoldre sèrie real) |
| `SERIEALB` | Equivalències de sèries d'albarà |
| `TRANS` | Mestre de transportistes |

Les queries són en `consultes_carregues.py`. Cap modificació al ERP, només `SELECT`.

---

## 6. Integracions externes

### 6.1 ERP SQL Server (lectura)

Origen de les càrregues reals. La connexió la dóna l'app germana via `PREPARACIO_PATH/.env`. Si el ERP cau, l'app retorna 503 a `/api/carregues`.

### 6.2 PreparacioComandesVenda (motor d'embalatges)

App germana ubicada a `P:\PreparacioComandesVenda` (Windows) o `/var/www/preparacio-comandes-venda` (Linux). `agregador.py` la carrega via `sys.path` i crida `motor.calcular_embalatges(sal, cpa)`. Sense aquesta app, l'agrupació no funciona (503 "Motor no disponible").

### 6.3 Power BI

Endpoint `/api/pbi/carregues` retorna les agrupacions desades amb format pla per a un dashboard. Protegit per header `X-Api-Key` i rate-limited a 30 req/min per IP. La clau viu a `.env` com `PBI_API_KEY`.

---

## 7. Errors habituals i resolució

| Símptoma | Causa probable | Diagnòstic | Resolució |
|---|---|---|---|
| Pàgina retorna 503 "Error de connexió amb la base de dades" | SQL Server caigut o credencials canviades | `journalctl -u agrupacio-carregues -n 50` busca `pyodbc.Error` | Verificar SQL Server. Comprovar `.env` (compartit amb app germana) |
| Pàgina retorna 503 "Motor no disponible" | L'app germana `PreparacioComandesVenda` no és accessible | Comprovar que existeix a `PREPARACIO_PATH` i que `motor.py` és importable | Restaurar/reiniciar app germana |
| 401 a `/api/carregues` | Sessió expirada | Cookie de sessió caducada | Re-login a `/login` |
| 403 CSRF a un POST | Token CSRF mal enviat o cookie regenerada | Mirar Network tab al navegador | Refrescar la pàgina amb `Ctrl+F5` |
| Migració PG falla amb "must be owner of relation" | Usuari `app_agrupacions` no és propietari de la taula | Provar com a `postgres` | Executar la migració com a `sudo -u postgres psql ...` |
| Després d'un deploy, els canvis no es veuen al navegador | Caché del navegador | F12 → Network → Disable cache | Hard reload `Ctrl+Shift+R` |
| Polling fa CPU alt | Bucle de polling sense aturar a finestra inactiva | Esperat (pausa quan pestanya s'amaga) | — |
| Pool PG esgotat ("pool exhausted") | Connexions filtrades per excepcions sense `finally` | `journalctl` busca "pool" | Reiniciar servei: `systemctl restart agrupacio-carregues.service` |
| `/control` no mostra una agrupació antiga amb el creador | Agrupació anterior a la migració `002` | `created_by_id` és NULL | Esperat — no hi havia traçabilitat abans |

---

## 8. Logs i monitorització

### 8.1 Logs de l'aplicació

| Tipus | Ubicació | Comanda |
|---|---|---|
| Log de l'app (Python, rotat 5×2MB) | `/var/www/agrupacio-carregues/agrupacio.log` | `tail -f agrupacio.log` |
| Log del servei (stdout/stderr de Gunicorn) | systemd journal | `journalctl -u agrupacio-carregues.service -f` |
| Errors de Gunicorn | També al journal | `journalctl -u agrupacio-carregues.service -n 100 -p err` |
| Audit log (a BD) | Taula `audit_logs` | `psql -d agrupaciocarregues -c "SELECT ts, user_name, accio, target FROM audit_logs ORDER BY ts DESC LIMIT 20"` |

### 8.2 Què mirar primer en cas d'incidència

1. `systemctl status agrupacio-carregues.service` — el servei està actiu?
2. `journalctl -u agrupacio-carregues -n 100` — què va passar abans del problema?
3. `tail -50 /var/www/agrupacio-carregues/agrupacio.log` — error específic de Python?
4. `curl http://127.0.0.1:5003/health` — quina dependència diu KO?

### 8.3 Health endpoint

`GET /health` retorna:
```json
{
  "ok": true,
  "db": {"ok": true, "msg": "..."},
  "motor": {"ok": true, "msg": "..."},
  "pg": {"ok": true, "msg": "..."}
}
```

En producció (`EXPOSE_HEALTH_DETAIL=false`) només es veuen els `ok` booleans.

---

## 9. Pla de contingència

### 9.1 Backup de PostgreSQL

L'estat propi de l'aplicació viu a la BD `agrupaciocarregues`. Backup diari recomanat:

```bash
# Crontab www-data, cada nit a les 02:00
0 2 * * * pg_dump -h localhost -U postgres -F c -d agrupaciocarregues \
              -f /var/backups/pg/agrupaciocarregues_$(date +\%Y\%m\%d).dump
```

Retenció recomanada: 30 dies.

### 9.2 Restauració

```bash
# Si cal restaurar una versió anterior
sudo systemctl stop agrupacio-carregues.service
pg_restore -h localhost -U postgres -d agrupaciocarregues_restored -c \
    /var/backups/pg/agrupaciocarregues_20260619.dump
# Renombrar BD si vol mantenir la nova com a oficial
sudo systemctl start agrupacio-carregues.service
```

### 9.3 Rollback de codi

Si una nova versió trenca producció:

```bash
sudo -u www-data git -C /var/www/agrupacio-carregues log --oneline -10
sudo -u www-data git -C /var/www/agrupacio-carregues checkout <commit_estable>
sudo systemctl restart agrupacio-carregues.service
```

> Atenció: si el rollback requereix desfer una migració de BD, cal fer-ho manualment (no hi ha rollback automàtic).

### 9.4 Identificar la versió desplegada

```bash
sudo -u www-data git -C /var/www/agrupacio-carregues log -1 --format="%h %s"
```

### 9.5 Què fer si cau el servei

1. `sudo systemctl status agrupacio-carregues.service`
2. Si "failed": `sudo journalctl -u agrupacio-carregues -n 100`. Si Python error, fix code o rollback.
3. Si "active (running)" però no respon: `sudo systemctl restart agrupacio-carregues.service`
4. Si el reinici no soluciona: comprovar dependències externes (PostgreSQL, SQL Server).

### 9.6 ERP SQL Server

Aquest no és gestionat per nosaltres. Si cau, l'app retorna 503 fins que es restableix. Contactar amb el proveïdor de l'ERP (vegeu **§ 10**).

---

## 10. Contactes i dependències externes

### 10.1 Contactes interns

| Rol | Nom | Contacte |
|---|---|---|
| Responsable tècnic | Oscar Hijazo | ohijazo@agrienergia.com |
| Responsable funcional (oficina) | Oscar Hijazo | ohijazo@agrienergia.com |
| IT (servidor `ae01farwebsrv`) | Jordi Coma | jcoma@agrienergia.com |

### 10.2 Dependències externes

| Servei | Proveïdor | Contacte |
|---|---|---|
| ERP SQL Server (`GWSV_AGRI`) | Kais | — |
| GitHub (repositori) | GitHub | — |
| Hosting (servidor intern) | `ae01farwebsrv.agrienergia.local` (192.168.11.244) | Jordi Coma (jcoma@agrienergia.com) |

### 10.3 Recursos addicionals

- `README.md` — guia per a desenvolupadors (setup local, tests).
- `ARCHITECTURE.md` — disseny tècnic detallat (capes, decisions, fluxos).
- `docs/guia-desplegament.html` — guia visual de desplegament.
- Codi font: https://github.com/ohijazo/Agrupador-de-Carregues
