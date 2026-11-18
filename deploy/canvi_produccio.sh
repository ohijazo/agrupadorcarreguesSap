#!/usr/bin/env bash
# =====================================================================
# Canvi a SAP de produccio: DB_FARIN_TEST -> DB_FARINERA
# Automatitza els passos 1-6 de docs/canvi_a_produccio.md, i hi afegeix
# l'herencia de KAIS: usuaris, agrupacions i els tres mesos de carregues del
# calendari (exportar_historic.py de l'app de KAIS -> importar_historic_kais.py).
#
#   sudo bash canvi_produccio.sh              # = --comprovar
#   sudo bash canvi_produccio.sh --comprovar  # nomes comprova, no toca res
#                                             # (inclou un assaig de l'herencia de KAIS)
#   sudo bash canvi_produccio.sh --executar   # fa el canvi (o marxa enrere si falla)
#   sudo bash canvi_produccio.sh --programar  # timer systemd: 23/11/2026 00:05
#   sudo bash canvi_produccio.sh --desprogramar
#
# Abans de canviar res comprova que s'arriba a DB_FARINERA per SQL i que
# l'usuari del Service Layer hi pot entrar. Si alguna cosa falla un cop
# comencat, torna els .env i PostgreSQL a l'estat d'abans. Si els .env ja
# apunten a DB_FARINERA, no fa res: es pot executar a ma abans del timer.
# =====================================================================
set -uo pipefail

MODE="${1:---comprovar}"
APP_DIR=/var/www/agrupacio-carregues-sap
MOTOR_DIR=/var/www/comandes-venda-sap
KAIS_DIR=/var/www/agrupacio-carregues          # app de KAIS (origen de l'historic)
KAIS_MOTOR_DIR=/var/www/comandes-venda
HISTORIC=/var/tmp/historic_kais.json
ENVS=("$APP_DIR/.env" "$MOTOR_DIR/.env")
TEST_DB=DB_FARIN_TEST
PROD_DB=DB_FARINERA
PG_DB=agrupaciocarregues_sap
SERVEI=agrupacio-carregues-sap
TIMERS=("$SERVEI-agregats.timer" "$SERVEI-agregats-complet.timer" "$SERVEI-pistolejat.timer")
SERVEIS=(comandes-venda-sap.service "$SERVEI.service")
HEALTH=http://127.0.0.1:50006/health
UNITAT=agrupacio-canvi-produccio
QUAN="2026-11-23 00:05:00"

log() { echo "$(date '+%F %T') $*"; }
mor() { log "ERROR: $*"; exit 1; }

[ "$EUID" -eq 0 ] || mor "s'ha d'executar amb sudo"

# ---------------------------------------------------------------- timer
if [ "$MODE" = "--programar" ]; then
    SCRIPT="$(readlink -f "$0")"
    cat > "/etc/systemd/system/$UNITAT.service" <<UNIT
[Unit]
Description=Canvi d'agrupacio-carregues-sap a SAP de produccio ($PROD_DB)
After=network-online.target postgresql.service

[Service]
Type=oneshot
ExecStart=/usr/bin/bash $SCRIPT --executar
UNIT
    cat > "/etc/systemd/system/$UNITAT.timer" <<UNIT
[Unit]
Description=Canvi a SAP de produccio el $QUAN

[Timer]
OnCalendar=$QUAN
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    systemctl enable --now "$UNITAT.timer"
    systemctl list-timers "$UNITAT.timer" --no-pager
    exit 0
fi
if [ "$MODE" = "--desprogramar" ]; then
    systemctl disable --now "$UNITAT.timer" 2>/dev/null || true
    rm -f "/etc/systemd/system/$UNITAT.timer" "/etc/systemd/system/$UNITAT.service"
    systemctl daemon-reload
    log "timer esborrat"
    exit 0
fi
[ "$MODE" = "--comprovar" ] || [ "$MODE" = "--executar" ] || mor "opcio desconeguda: $MODE"

# ---------------------------------------------------------- ja està fet?
pendents=0
for f in "${ENVS[@]}"; do
    [ -f "$f" ] || mor "no existeix $f"
    n=$(grep -cE "=${TEST_DB}\r?$" "$f" || true)
    log "$f: $n linies amb $TEST_DB"
    pendents=$((pendents + n))
done
if [ "$pendents" -eq 0 ]; then
    log "Els .env ja no apunten a $TEST_DB: no hi ha res a fer."
    exit 0
fi

# ---------------------------------------------------- comprovacions prèvies
log "Comprovant $PROD_DB (SQL i Service Layer)..."
sudo -u www-data "$APP_DIR/venv/bin/python" - "$APP_DIR/.env" "$PROD_DB" <<'PY' || mor "les comprovacions han fallat: no s'ha tocat res"
import sys, pyodbc, requests, urllib3
urllib3.disable_warnings()
env = {}
for l in open(sys.argv[1]):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); env[k.strip()] = v.strip()
bd = sys.argv[2]
ok = True
try:
    c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={env['SAP_SQL_SERVER']};DATABASE={bd};"
        f"UID={env['SAP_SQL_USER']};PWD={env['SAP_SQL_PASSWORD']};"
        "TrustServerCertificate=yes;ApplicationIntent=ReadOnly;", timeout=10).cursor()
    for t in ("ORDR", "ODLN"):
        print(f"  SQL  {bd} {t}: {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} files")
except Exception as e:
    print(f"  SQL  ERROR: {e}"); ok = False
try:
    url = env["SAP_SL_URL"].rstrip("/")
    verify = env.get("SAP_SL_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
    s = requests.Session()
    r = s.post(f"{url}/Login", json={"CompanyDB": bd, "UserName": env["SAP_SL_USER"],
               "Password": env["SAP_SL_PASSWORD"]}, verify=verify, timeout=20)
    if r.status_code == 200:
        print(f"  SL   login OK a {bd} amb {env['SAP_SL_USER']}")
        s.post(f"{url}/Logout", verify=verify, timeout=10)
    else:
        print(f"  SL   ERROR HTTP {r.status_code}: {r.text[:200]}"); ok = False
except Exception as e:
    print(f"  SL   ERROR: {e}"); ok = False
sys.exit(0 if ok else 1)
PY

# Herencia de KAIS: exportar (nomes llegeix KAIS) i importar a PostgreSQL.
# A --comprovar la importacio es fa en simulacio (es desfa al final).
exporta_kais() {
    log "Exportant l'historic de KAIS -> $1"
    sudo -u www-data "$KAIS_DIR/venv/bin/python" "$KAIS_DIR/scripts/exportar_historic.py"         --sortida "$1" 2>&1 | grep -v '\[INFO\]'
    [ "${PIPESTATUS[0]}" -eq 0 ] && [ -s "$1" ]
}
importa_kais() {
    log "Important l'historic de KAIS $2"
    sudo -u www-data env KAIS_APP_PATH="$KAIS_MOTOR_DIR" "$APP_DIR/venv/bin/python"         "$APP_DIR/scripts/importar_historic_kais.py" "$1" $2 2>&1 | grep -v '\[INFO\]'
    [ "${PIPESTATUS[0]}" -eq 0 ]
}

if [ "$MODE" = "--comprovar" ]; then
    PROVA=/var/tmp/historic_kais_prova.json
    exporta_kais "$PROVA" || mor "l'exportacio de KAIS ha fallat"
    importa_kais "$PROVA" --simular || mor "la importacio (simulada) ha fallat"
    rm -f "$PROVA"
    log "Comprovacions OK. Amb --executar es faria el canvi."
    exit 0
fi

# --------------------------------------------------------------- canvi
BK="/root/canvi-produccio-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK"
cp "$APP_DIR/.env"   "$BK/agrupacio-sap.env"
cp "$MOTOR_DIR/.env" "$BK/comandes-sap.env"
sudo -u postgres pg_dump -Fc "$PG_DB" > "$BK/$PG_DB.dump" || mor "pg_dump ha fallat: no s'ha tocat res"
log "Copies a $BK"

enrere() {
    log "ERROR: $1 -- TORNANT ENRERE"
    systemctl stop "${SERVEIS[@]}" || true
    cp "$BK/agrupacio-sap.env" "$APP_DIR/.env"
    cp "$BK/comandes-sap.env"  "$MOTOR_DIR/.env"
    sudo -u postgres pg_restore --clean --if-exists -d "$PG_DB" "$BK/$PG_DB.dump" || log "pg_restore amb avisos"
    systemctl start "${SERVEIS[@]}" || true
    systemctl start "${TIMERS[@]}" || true
    log "Marxa enrere feta: l'app torna a $TEST_DB. Revisar aquest log."
    exit 1
}

systemctl stop "${TIMERS[@]}"
systemctl stop "${SERVEIS[@]}" || enrere "no s'han pogut aturar els serveis"

for f in "${ENVS[@]}"; do
    sed -i -E "s/=${TEST_DB}(\r?)$/=${PROD_DB}\1/" "$f" || enrere "sed a $f"
    grep -qE "=${TEST_DB}\r?$" "$f" && enrere "$f encara te $TEST_DB"
    log "$f -> $PROD_DB"
done

sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$PG_DB" <<'SQL' || enrere "buidat de PostgreSQL"
BEGIN;
TRUNCATE agrupacions CASCADE;
TRUNCATE kais_carrega_snapshot, kais_carrega_override,
         ordre_carrega_cache, albarans_cancelats;
UPDATE agregats_meta SET ultim_refresc_complet = NULL, ultim_refresc_incr = NULL,
                         ultim_error = NULL, comandes = 0;
COMMIT;
SQL
log "PostgreSQL: dades de proves buidades (usuaris i auditoria es conserven)"

exporta_kais "$HISTORIC" || enrere "exportacio de l'historic de KAIS"
importa_kais "$HISTORIC" || enrere "importacio de l'historic de KAIS"

systemctl start "${SERVEIS[@]}" || enrere "no arrenquen els serveis"
systemctl start "$SERVEI-agregats-complet.service" || enrere "refresc complet dels agregats"
systemctl start "${TIMERS[@]}" || enrere "no arrenquen els timers"

for i in $(seq 1 12); do
    resp=$(curl -s -m 10 "$HEALTH" || true)
    if echo "$resp" | grep -q '"ok":true' && ! echo "$resp" | grep -q '"ok":false'; then
        log "health OK: $resp"
        log "CANVI FET: agrupacio-carregues-sap i comandes-venda-sap llegeixen de $PROD_DB"
        exit 0
    fi
    sleep 5
done
enrere "health no respon OK: $resp"
