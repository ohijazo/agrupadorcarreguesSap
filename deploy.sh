#!/bin/bash
# ==============================================================
# Script de desplegament - Agrupador de Carregues **variant SAP B1**
# ==============================================================
# Us:   sudo bash deploy.sh [--first-install]
#
#   --first-install   Primera instal·lacio (clona repo, venv, PostgreSQL,
#                     systemd, Apache, logrotate)
#   (sense arguments) Actualitza a l'ultima versio de GitHub
#
# NOTA: aquesta es la variant SAP. NO toca la variant Kais, que viu a
# /var/www/agrupacio-carregues, servei `agrupacio-carregues`, port 50004,
# BD `agrupaciocarregues` i URL agrupacions.agrienergia.local.
#
# Dependencia obligatoria: l'app germana SAP (motor d'embalatges) ha
# d'estar desplegada a /var/www/comandes-venda-sap ABANS que aquesta.
# ==============================================================

set -e

# ---- Configuracio ----
REPO_URL="https://github.com/ohijazo/agrupadorcarreguesSap.git"
APP_DIR="/var/www/agrupacio-carregues-sap"
SERVICE_NAME="agrupacio-carregues-sap"
PYTHON_BIN="python3"
VENV_DIR="$APP_DIR/venv"
# 50005 el te el DeCA; 5000/5001/5002/50002/50003/50004 tambe estan ocupats.
APP_PORT=50006
APP_USER="www-data"
SERVER_NAME="agrupacions-sap.agrienergia.local"

# App germana SAP: d'alla surt motor.py (calcul d'embalatges)
PREPARACIO_PATH="/var/www/comandes-venda-sap"
# Kais canonic: d'alla surten models/regles/mailer, via el _bootstrap de
# comandes-venda-sap. Aqui nomes el comprovem.
KAIS_PATH="/var/www/comandes-venda"

# PostgreSQL (separat de la BD Kais)
PG_DB="agrupaciocarregues_sap"
PG_APP_USER="app_agrupacions_sap"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[AVIS]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ---- Verificar que s'executa com a root ----
if [ "$EUID" -ne 0 ]; then
    error "Cal executar amb sudo: sudo bash deploy.sh"
fi

# ---- Aplicar schema + migracions (idempotent, reutilitzat pels dos modes) ----
aplicar_sql() {
    local pg_pass="$1"

    info "Carregant db/schema.sql..."
    PGPASSWORD="$pg_pass" psql -h localhost -U "$PG_APP_USER" -d "$PG_DB" \
        -v ON_ERROR_STOP=1 -q -f "$APP_DIR/db/schema.sql"

    for mig in "$APP_DIR"/db/migrations/*.sql; do
        [ -f "$mig" ] || continue
        info "Migracio: $(basename "$mig")"
        PGPASSWORD="$pg_pass" psql -h localhost -U "$PG_APP_USER" -d "$PG_DB" \
            -v ON_ERROR_STOP=1 -q -f "$mig"
    done
}

# ---- Llegir una variable del .env desplegat ----
llegir_env() {
    grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-
}

# ---- Unitats systemd (servei + timers dels agregats) ----------------
# En una funcio, i no nomes dins del --first-install, perque el mode
# ACTUALITZACIO tambe les ha de sincronitzar: si no, una instal·lacio
# anterior no veuria mai els timers nous ni els canvis a la unitat del
# servei. Tot el que fa es idempotent.
instal_la_unitats() {
    info "Instal·lant o actualitzant el servei systemd (Gunicorn)..."
    cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=Agrupador de Carregues (variant SAP B1)
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=PORT=$APP_PORT
Environment=KAIS_APP_PATH=$KAIS_PATH
ExecStart=$VENV_DIR/bin/gunicorn \\
    --bind 127.0.0.1:$APP_PORT \\
    --workers 2 \\
    --timeout 120 \\
    --access-logfile $APP_DIR/access.log \\
    --access-logformat '%(h)s %(t)s "%(r)s" %(s)s %(b)s %(L)ss' \\
    --error-logfile $APP_DIR/error.log \\
    app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"

    # ---- Refrescador dels agregats per carrega ----
    # El llistat necessita kg_total, num_comandes, palletitzable i is_granel,
    # i el Service Layer no els pot calcular: no permet agregar ni filtrar
    # sobre linies de document, i portar-se les linies a cada peticio son 247
    # camps i ~19 KB per comanda (una pagina del llistat son 500 carregues).
    # Per aixo es precalculen a PostgreSQL amb aquests timers.
    #
    # Nomes fan falta si SAP_BACKEND_LLISTAR_CARREGUES=sl. S'instal·len
    # igualment: estan actius pero son inofensius mentre el llistat vagi per
    # SQL, i aixi la taula ja esta calenta el dia que es commuti.
    info "Instal·lant o actualitzant el refrescador d'agregats..."
    cat > "/etc/systemd/system/${SERVICE_NAME}-agregats.service" <<UNITAGR
[Unit]
Description=Refresc dels agregats per carrega (variant SAP B1)
After=network.target postgresql.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=KAIS_APP_PATH=$KAIS_PATH
ExecStart=$VENV_DIR/bin/python $APP_DIR/scripts/refrescar_agregats.py
UNITAGR

    cat > "/etc/systemd/system/${SERVICE_NAME}-agregats.timer" <<TIMERAGR
[Unit]
Description=Refresc incremental dels agregats cada 2 minuts

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
AccuracySec=15s

[Install]
WantedBy=timers.target
TIMERAGR

    cat > "/etc/systemd/system/${SERVICE_NAME}-agregats-complet.service" <<UNITAGRC
[Unit]
Description=Reconstruccio completa dels agregats per carrega (variant SAP B1)
After=network.target postgresql.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=KAIS_APP_PATH=$KAIS_PATH
ExecStart=$VENV_DIR/bin/python $APP_DIR/scripts/refrescar_agregats.py --complet
UNITAGRC

    cat > "/etc/systemd/system/${SERVICE_NAME}-agregats-complet.timer" <<TIMERAGRC
[Unit]
Description=Reconstruccio completa dels agregats, de matinada

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
TIMERAGRC

    systemctl daemon-reload
    systemctl enable --now "${SERVICE_NAME}-agregats.timer"
    systemctl enable --now "${SERVICE_NAME}-agregats-complet.timer"
}

# ==============================================================
# PRIMERA INSTAL·LACIO
# ==============================================================
if [ "$1" == "--first-install" ]; then
    info "=== Primera instal·lacio (variant SAP) ==="

    # ---- Preflight: dependencies externes ----
    if [ ! -d "$PREPARACIO_PATH" ]; then
        error "No existeix $PREPARACIO_PATH. Desplega primer l'app germana SAP
       (repo PreparacioComandesVendaSAP, el seu deploy.sh --first-install).
       Sense ella, /api/agrupar no pot calcular embalatges."
    fi
    if [ ! -f "$PREPARACIO_PATH/motor.py" ]; then
        error "$PREPARACIO_PATH existeix pero no hi ha motor.py. Instal·lacio incompleta?"
    fi
    # La capa de lectura del Service Layer viu a l'app germana (una sola copia
    # del codi de sessio, compartida per les dues apps). Si alla encara hi ha
    # una versio anterior, aquesta app peta amb un ImportError en arrencar;
    # millor avortar aqui amb un missatge que es pugui llegir.
    if [ ! -f "$PREPARACIO_PATH/sl_lectura/client.py" ]; then
        error "Falta $PREPARACIO_PATH/sl_lectura/. Actualitza primer l'app germana
       (cd $PREPARACIO_PATH && sudo -u $APP_USER git pull) i torna-ho a provar."
    fi
    # El _bootstrap.py de comandes-venda-sap resol models/regles/mailer a
    # KAIS_APP_PATH. El seu .env NO el defineix: el seu servei el passa per
    # Environment= a la unitat systemd. Com que nosaltres importem motor.py
    # dins del nostre proces, l'hem de passar nosaltres tambe (ho fem a la
    # nostra unitat, mes avall). Sense aixo, _bootstrap buscaria a
    # /var/www/preparacioComandesVenda, que no existeix, i /health diria
    # motor: false.
    if [ ! -d "$KAIS_PATH" ]; then
        error "No existeix $KAIS_PATH (Kais canonic). El motor d'embalatges hi
       resol models/regles/mailer i sense ell l'app no arrenca."
    fi

    # ---- Dependencies del sistema ----
    info "Instal·lant dependencies del sistema..."
    apt-get update -qq
    apt-get install -y -qq git python3 python3-venv python3-pip postgresql-client > /dev/null

    # ---- Driver ODBC per SQL Server ----
    if ! odbcinst -q -d 2>/dev/null | grep -qi "ODBC Driver"; then
        info "Instal·lant driver ODBC per SQL Server..."
        curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
        . /etc/os-release
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/$VERSION_ID/prod $VERSION_CODENAME main" > /etc/apt/sources.list.d/mssql-release.list
        apt-get update -qq
        ACCEPT_EULA=Y apt-get install -y -qq msodbcsql18 unixodbc-dev > /dev/null
        info "Driver ODBC instal·lat"
    else
        info "Driver ODBC ja instal·lat"
    fi

    # ---- Clonar repositori ----
    if [ -d "$APP_DIR" ]; then
        warn "$APP_DIR ja existeix. Fent backup..."
        mv "$APP_DIR" "$APP_DIR.bak.$(date +%Y%m%d%H%M%S)"
    fi
    info "Clonant repositori..."
    git clone "$REPO_URL" "$APP_DIR"

    # ---- Entorn virtual ----
    info "Creant entorn virtual..."
    $PYTHON_BIN -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
    "$VENV_DIR/bin/pip" install gunicorn -q

    # El motor de l'app germana importa les seves propies dependencies:
    # cal tenir-les al MATEIX venv perque l'import funcioni.
    if [ -f "$PREPARACIO_PATH/requirements.txt" ]; then
        info "Instal·lant dependencies de l'app germana ($PREPARACIO_PATH)..."
        "$VENV_DIR/bin/pip" install -r "$PREPARACIO_PATH/requirements.txt" -q
    fi

    # ---- PostgreSQL ----
    info "Configurant PostgreSQL..."
    PG_PASS=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(24))")

    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PG_APP_USER'" | grep -q 1; then
        warn "El rol $PG_APP_USER ja existeix: li posem la contrasenya nova."
        sudo -u postgres psql -q -c "ALTER ROLE $PG_APP_USER WITH LOGIN PASSWORD '$PG_PASS';"
    else
        sudo -u postgres psql -q -c "CREATE ROLE $PG_APP_USER WITH LOGIN PASSWORD '$PG_PASS';"
    fi

    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1; then
        warn "La BD $PG_DB ja existeix: no la toquem (les dades es conserven)."
    else
        sudo -u postgres psql -q -c "CREATE DATABASE $PG_DB OWNER $PG_APP_USER ENCODING 'UTF8';"
        sudo -u postgres psql -q -c "GRANT ALL PRIVILEGES ON DATABASE $PG_DB TO $PG_APP_USER;"
    fi

    # PostgreSQL 15+: el schema public no es escrivible encara que tinguis
    # ALL PRIVILEGES sobre la BD. Sense aixo, schema.sql peta amb
    # "permission denied for schema public".
    sudo -u postgres psql -q -d "$PG_DB" -c "ALTER SCHEMA public OWNER TO $PG_APP_USER;"
    sudo -u postgres psql -q -d "$PG_DB" -c "GRANT CREATE, USAGE ON SCHEMA public TO $PG_APP_USER;"

    aplicar_sql "$PG_PASS"

    # ---- Fitxer .env ----
    if [ -f "$APP_DIR/.env" ]; then
        warn ".env ja existeix (del backup?). No el sobreescrivim."
    else
        info "Generant .env amb secrets aleatoris..."
        SECRET_KEY=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(48))")
        ADMIN_KEY=$($PYTHON_BIN -c "import secrets; print(secrets.token_urlsafe(24))")
        cat > "$APP_DIR/.env" <<ENVFILE
# Generat per deploy.sh --first-install. Ompli els camps CANVIA_*.
# Referencia completa: deploy/env.production.example

# --- SAP B1 SQL Server (nomes lectura) ---
SAP_SQL_SERVER=AE01SAPSQL.Agrienergia.local
SAP_SQL_DATABASE=DB_FARIN_TEST
SAP_SQL_USER=sa
SAP_SQL_PASSWORD=CANVIA_AQUESTA_CONTRASENYA

SQL_SERVER=AE01SAPSQL.Agrienergia.local
SQL_DATABASE=DB_FARIN_TEST
SQL_USER=sa
SQL_PASSWORD=CANVIA_AQUESTA_CONTRASENYA

# --- App germana SAP (motor d'embalatges) ---
# KAIS_APP_PATH no va aqui: el passa la unitat systemd.
PREPARACIO_PATH=$PREPARACIO_PATH

# --- Backend de dades: sql | sl ---
# Les lectures s'estan migrant al Service Layer. Commutar es editar aquesta
# linia (o la de la funcio concreta) i reiniciar el servei. Vegeu
# deploy/env.production.example per a la llista de variables.
SAP_BACKEND=sql
SAP_BACKEND_FALLBACK=off

# --- Seguretat administracio ---
ADMIN_KEY=$ADMIN_KEY

# --- PostgreSQL ---
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=$PG_DB
PG_USER=$PG_APP_USER
PG_PASSWORD=$PG_PASS
PG_POOL_MIN=1
PG_POOL_MAX=5

# --- Auth ---
AUTH_ENABLED=true
FLASK_SECRET_KEY=$SECRET_KEY

# --- Health ---
EXPOSE_HEALTH_DETAIL=false

# --- Power BI (opcional) ---
PBI_API_KEY=

# --- SAP Service Layer (fase futura d'escriptura) ---
SAP_SL_URL=https://192.168.11.238:50000/b1s/v1
SAP_SL_COMPANY=DB_FARIN_TEST
SAP_SL_USER=OHijazo
SAP_SL_PASSWORD=CANVIA_AQUESTA_CONTRASENYA
SAP_SL_VERIFY_SSL=false
SAP_SL_TIMEOUT=15
ENVFILE
    fi
    chmod 600 "$APP_DIR/.env"

    # ---- Permisos ----
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"

    # ---- logrotate ----
    info "Instal·lant configuracio logrotate..."
    cp "$APP_DIR/deploy/logrotate/$SERVICE_NAME" "/etc/logrotate.d/$SERVICE_NAME"
    chmod 644 "/etc/logrotate.d/$SERVICE_NAME"

    # ---- Servei systemd ----
    # EnvironmentFile va ABANS de Environment: systemd aplica les variables
    # en ordre d'aparicio, aixi PORT=$APP_PORT guanya sobre un PORT del .env.
    instal_la_unitats

    # ---- Apache ----
    info "Configurant Apache..."
    a2enmod proxy proxy_http headers expires > /dev/null 2>&1 || true
    cp "$APP_DIR/deploy/apache/${SERVICE_NAME}.conf" "/etc/apache2/sites-available/${SERVICE_NAME}.conf"
    a2ensite "${SERVICE_NAME}.conf" > /dev/null
    if apache2ctl configtest 2>&1 | grep -q "Syntax OK"; then
        systemctl reload apache2
        info "Apache recarregat (vhost $SERVER_NAME actiu)"
    else
        warn "apache2ctl configtest ha fallat. Revisa-ho i fes: sudo systemctl reload apache2"
    fi

    # NO arrenquem el servei: falten les credencials SAP al .env.
    info ""
    info "=== Instal·lacio estructural completada ==="
    warn "FALTA: posar les credencials SAP al .env (camps CANVIA_*)."
    info "1) sudo nano $APP_DIR/.env    # SQL_PASSWORD / SAP_SQL_PASSWORD / SAP_SL_PASSWORD"
    info "2) sudo systemctl start $SERVICE_NAME"
    info "3) curl -s http://127.0.0.1:$APP_PORT/health    # ha de dir db/pg/motor ok"
    info "4) Crear el primer usuari admin:"
    info "     cd $APP_DIR && sudo -u $APP_USER venv/bin/python scripts/crear_admin.py"
    info "5) Demanar al DNS corporatiu una entrada A/CNAME:"
    info "     $SERVER_NAME -> ae01farwebsrv.agrienergia.local"
    info "6) Primera carrega dels agregats del llistat:"
    info "     sudo systemctl start ${SERVICE_NAME}-agregats-complet"
    info "7) Provar: http://$SERVER_NAME/"
    info ""
    info "Comandes utils:"
    info "  systemctl {start|stop|restart|status} $SERVICE_NAME"
    info "  journalctl -u $SERVICE_NAME -f"
    info "  tail -f $APP_DIR/access.log $APP_DIR/error.log $APP_DIR/agrupacio.log"
    exit 0
fi

# ==============================================================
# ACTUALITZACIO
# ==============================================================
info "=== Actualitzant aplicacio (variant SAP) ==="

[ -d "$APP_DIR" ] || error "$APP_DIR no existeix. Executa primer: sudo bash deploy.sh --first-install"
[ -d "$VENV_DIR" ] || error "Entorn virtual no trobat a $VENV_DIR"
[ -f "$PREPARACIO_PATH/sl_lectura/client.py" ] || error "Falta $PREPARACIO_PATH/sl_lectura/.
       Actualitza primer l'app germana: cd $PREPARACIO_PATH && sudo -u $APP_USER git pull"

cd "$APP_DIR"

# Executem git com l'usuari propietari per evitar el "dubious ownership"
# que Git modern rebutja quan root toca un repo d'un altre usuari.
GIT_AS_APP="sudo -u $APP_USER git"

OLD_COMMIT=$($GIT_AS_APP rev-parse --short HEAD 2>/dev/null || echo "desconegut")
info "Versio actual: $OLD_COMMIT"

info "Descarregant ultima versio de GitHub..."
$GIT_AS_APP fetch origin
$GIT_AS_APP reset --hard origin/main

NEW_COMMIT=$($GIT_AS_APP rev-parse --short HEAD)

# Les unitats es sincronitzen ABANS de comprovar si hi ha versio nova, i hi ha
# un motiu que costa un desplegament d'aprendre: aquest script s'actualitza a
# si mateix amb el `git reset --hard` de sobre, pero bash ja ha llegit el
# fitxer. Per tant la execucio que PORTA una millora del desplegament encara
# aplica la logica VELLA; la nova no entra en vigor fins a la seguent. I si
# aquella seguent no te res a baixar i surt per l'early exit, no s'aplica mai.
# Posant-ho aqui, una execucio sense canvis tambe convergeix.
instal_la_unitats

if [ "$OLD_COMMIT" == "$NEW_COMMIT" ]; then
    info "Ja estas a l'ultima versio ($NEW_COMMIT). Unitats sincronitzades."
    info "Si has canviat la unitat del servei, cal reiniciar-lo:"
    info "  sudo systemctl restart $SERVICE_NAME"
    exit 0
fi
info "Nova versio: $NEW_COMMIT"

if $GIT_AS_APP diff "$OLD_COMMIT" "$NEW_COMMIT" -- requirements.txt | grep -q .; then
    info "Actualitzant dependencies Python..."
    "$VENV_DIR/bin/pip" install -r requirements.txt -q
else
    info "Dependencies sense canvis"
fi

# Migracions noves o modificades -> reaplicar-ho tot (son idempotents)
if $GIT_AS_APP diff "$OLD_COMMIT" "$NEW_COMMIT" -- db/ | grep -q .; then
    info "Canvis a db/: reaplicant schema + migracions..."
    PG_PASS=$(llegir_env PG_PASSWORD)
    [ -n "$PG_PASS" ] || error "No he pogut llegir PG_PASSWORD de $APP_DIR/.env"
    aplicar_sql "$PG_PASS"
else
    info "Sense canvis a db/"
fi

if $GIT_AS_APP diff "$OLD_COMMIT" "$NEW_COMMIT" -- "deploy/logrotate/$SERVICE_NAME" | grep -q .; then
    info "Actualitzant configuracio logrotate..."
    cp "$APP_DIR/deploy/logrotate/$SERVICE_NAME" "/etc/logrotate.d/$SERVICE_NAME"
    chmod 644 "/etc/logrotate.d/$SERVICE_NAME"
fi

if $GIT_AS_APP diff "$OLD_COMMIT" "$NEW_COMMIT" -- "deploy/apache/${SERVICE_NAME}.conf" | grep -q .; then
    info "Actualitzant VirtualHost Apache..."
    cp "$APP_DIR/deploy/apache/${SERVICE_NAME}.conf" "/etc/apache2/sites-available/${SERVICE_NAME}.conf"
    if apache2ctl configtest 2>&1 | grep -q "Syntax OK"; then
        systemctl reload apache2
    else
        warn "apache2ctl configtest ha fallat: no recarrego Apache."
    fi
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

info "Reiniciant servei..."
systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    info "=== Actualitzacio completada ==="
    info "Versio: $OLD_COMMIT -> $NEW_COMMIT"
    info "Canvis: git log --oneline $OLD_COMMIT..$NEW_COMMIT"
    curl -fsS "http://127.0.0.1:$APP_PORT/health" && echo "" || warn "/health no respon encara"
else
    error "El servei no ha arrencat. Revisar: sudo journalctl -u $SERVICE_NAME -n 50"
fi
