# Desplegament — Agrupador de Càrregues (variant SAP B1)

Guia per instal·lar aquesta variant **al costat** de la variant Kais que ja corre
en producció, sense tocar-la.

> La guia llarga d'Ubuntu (`docs/guia-desplegament.html`) descriu la instal·lació
> de la **variant Kais**. Aquest document és el delta per a la variant SAP: què
> canvia, i com fer-ho amb `deploy.sh`.

## 1. Les dues variants, una al costat de l'altra

| | Kais (en producció) | SAP B1 (aquesta) |
|---|---|---|
| Directori | `/var/www/agrupacio-carregues` | `/var/www/agrupacio-carregues-sap` |
| Servei systemd | `agrupacio-carregues` | `agrupacio-carregues-sap` |
| Port intern (Gunicorn) | 50004 | **50006** |
| URL | `agrupacions.agrienergia.local` | **`agrupacions-sap.agrienergia.local`** |
| Base de dades PostgreSQL | `agrupaciocarregues` | **`agrupaciocarregues_sap`** |
| Usuari PostgreSQL | `app_agrupacions` | **`app_agrupacions_sap`** |
| Origen de dades | SQL Server `vkais:50058` | SQL Server `AE01SAPSQL` (`DB_FARIN_TEST`) |
| Motor d'embalatges | `/var/www/comandes-venda` | **`/var/www/comandes-venda-sap`** |
| Repositori | `Agrupador-de-Carregues` | `agrupadorcarreguesSap` |

Les dues BD són **separades a propòsit**: els `carrega_id` de Kais i de SAP no són
compatibles i barrejar-los corrompria les agrupacions.

## 2. Prerequisits

1. **L'app germana SAP ha d'estar desplegada primer** a `/var/www/comandes-venda-sap`
   (repo `PreparacioComandesVendaSAP`, amb el seu `deploy.sh --first-install`).
   D'allà surt `motor.py`, que calcula els embalatges. Sense això, `/api/agrupar` peta.

   Comprovació ràpida al servidor:
   ```bash
   ls /var/www/comandes-venda-sap/motor.py
   systemctl is-active comandes-venda-sap
   ```

2. **El Kais canònic** (`/var/www/comandes-venda`) ha d'existir: el `_bootstrap.py`
   de `comandes-venda-sap` hi va a buscar els mòduls compartits `models`, `regles`
   i `mailer`.

3. **Connectivitat cap a SAP**: el servidor Ubuntu ha d'arribar a
   `AE01SAPSQL.Agrienergia.local` pel port de SQL Server.
   ```bash
   nc -zv AE01SAPSQL.Agrienergia.local 1433
   ```

4. **Codi pujat a GitHub**: `deploy.sh` clona de `origin/main`. Assegura't que no
   et queden commits locals sense pujar (`git push`).

## 3. Instal·lació

```bash
# Al servidor (ae01farwebsrv, 192.168.11.244)
cd /tmp
git clone https://github.com/ohijazo/agrupadorcarreguesSap.git agrup-sap-tmp
sudo bash agrup-sap-tmp/deploy.sh --first-install
```

El script fa, en aquest ordre:

1. Comprova els prerequisits (app germana i Kais canònic).
2. Instal·la paquets del sistema i, si cal, el driver ODBC de SQL Server.
3. Clona el repo a `/var/www/agrupacio-carregues-sap`.
4. Crea el venv i instal·la `requirements.txt` + `gunicorn` + **les dependències
   de l'app germana** (les necessita `motor.py` per importar-se).
5. Crea el rol i la BD PostgreSQL amb **contrasenya generada aleatòriament**,
   arregla el propietari del schema `public` (necessari a PostgreSQL 15+) i
   carrega `db/schema.sql` + totes les migracions (idempotents).
6. Genera `/var/www/agrupacio-carregues-sap/.env` (mode 600) amb la contrasenya
   de PG, `FLASK_SECRET_KEY` i `ADMIN_KEY` ja plens.
7. Instal·la logrotate, el servei systemd (`enable`, **sense arrencar**) i el
   VirtualHost d'Apache.

### 3.1 Passos manuals que queden

```bash
# 1. Credencials SAP (els camps CANVIA_* del .env)
sudo nano /var/www/agrupacio-carregues-sap/.env

# 2. Arrencar
sudo systemctl start agrupacio-carregues-sap
sudo systemctl status agrupacio-carregues-sap

# 3. Verificar dependències (db = SQL Server SAP, pg = PostgreSQL, motor = embalatges)
curl -s http://127.0.0.1:50006/health
# esperat: {"db":{"ok":true},"motor":{"ok":true},"ok":true,"pg":{"ok":true}}

# 4. Primer usuari admin (demana la contrasenya per stdin)
cd /var/www/agrupacio-carregues-sap
sudo -u www-data venv/bin/python scripts/crear_admin.py --username tu@agrienergia.com --nom "El teu nom"

# 5. DNS: demanar l'entrada al servidor DNS corporatiu
#    agrupacions-sap.agrienergia.local  ->  ae01farwebsrv.agrienergia.local

# 6. Provar des d'un PC de la xarxa
#    http://agrupacions-sap.agrienergia.local/
```

## 4. Actualitzacions

```bash
sudo bash /var/www/agrupacio-carregues-sap/deploy.sh
```

Fa `git fetch` + `reset --hard origin/main`, reinstal·la dependències només si
`requirements.txt` ha canviat, reaplica schema i migracions si ha canviat `db/`,
sincronitza logrotate i el vhost si han canviat, reinicia el servei i comprova
`/health`.

## 5. Detalls que és fàcil equivocar

- **`AllowEncodedSlashes NoDecode` + `nocanon`** al vhost són imprescindibles: els
  `carrega_id` tenen format `2026/01/0002266` i viatgen com a `%2F` dins la URL.
  Sense això, Apache respon 404.
- **`KAIS_APP_PATH` va a la unitat systemd, no al `.env`.** El `_bootstrap.py` de
  `comandes-venda-sap` hi resol `models`/`regles`/`mailer`. Al servidor, el `.env`
  de `comandes-venda-sap` **no** el defineix: cada servei se'l passa per
  `Environment=`. Com que nosaltres importem `motor.py` dins del nostre procés,
  l'hem de passar nosaltres (`Environment=KAIS_APP_PATH=/var/www/comandes-venda`,
  ho fa el `deploy.sh`). Sense això, `_bootstrap` el buscaria a
  `/var/www/preparacioComandesVenda`, que no existeix, i `/health` diria
  `motor: false`.
  En local (Windows) no cal: allà el `.env` de `P:\preparacioComandesVendaSAP` sí
  que el defineix, i `app.py` el carrega com a *fallback*.
- **Un sol venv per a les dues apps.** `motor.py` viu a `comandes-venda-sap` però
  s'importa dins del procés d'aquesta app, així que les seves dependències han
  d'estar instal·lades al venv d'aquí (ho fa el `deploy.sh`).
- **PostgreSQL 15+**: `ALL PRIVILEGES` sobre la BD no dóna permís d'escriptura al
  schema `public`. Cal `ALTER SCHEMA public OWNER` (el `deploy.sh` ho fa).
- **`agrupacio.log`** el rota l'aplicació mateixa (`RotatingFileHandler`, 2 MB × 5).
  El logrotate del sistema només toca `access.log` i `error.log` de Gunicorn.
- **Compte amb els caràcters del `.env`**: el `systemd` el llegeix com a
  `EnvironmentFile`, i allà un `#` dins d'un valor comença un comentari i els
  espais no citats trenquen la línia. Si la contrasenya SAP en té, posa-la entre
  cometes simples: `SQL_PASSWORD='la meva#clau'`.
- **Port 50006**: el fixa el `systemd` (`Environment=PORT=50006`, després de
  l'`EnvironmentFile`) i el `--bind` de Gunicorn. El `PORT` del `.env` de
  desenvolupament (5004) no hi pinta res.

## 6. Diagnòstic

| Símptoma | Causa probable | Comprovació |
|---|---|---|
| `motor: ok=false` a `/health` | Falta `comandes-venda-sap` o les seves dependències | `sudo -u www-data venv/bin/python -c "import app, motor; print(motor.calcular_embalatges)"` |
| `db: ok=false` | No arriba a `AE01SAPSQL` o credencials dolentes | `nc -zv AE01SAPSQL.Agrienergia.local 1433` |
| `pg: ok=false` | Contrasenya del `.env` desincronitzada amb el rol PG | `sudo -u postgres psql -c "ALTER ROLE app_agrupacions_sap WITH PASSWORD '...'"` |
| 404 en obrir una càrrega | Falta `AllowEncodedSlashes NoDecode` al vhost | `apache2ctl -S` i revisar el fitxer del site |
| El servei no arrenca | Error a l'import o al `.env` | `sudo journalctl -u agrupacio-carregues-sap -n 50` |

## 7. Fitxers d'aquest kit

```
deploy.sh                                     # instal·lació i actualització
deploy/apache/agrupacio-carregues-sap.conf    # VirtualHost
deploy/logrotate/agrupacio-carregues-sap      # rotació dels logs de Gunicorn
deploy/postgres/setup_prod_sap.sql            # creació de rol + BD (referència manual)
deploy/env.production.example                 # referència del .env de producció
```

## 8. Backend de dades: SQL Server o Service Layer

SAP no suporta llegir les seves taules per SQL directe, i les lectures s'han
migrat al **Service Layer**. Les dues implementacions conviuen i es commuten des
del `.env`, així que revertir és canviar una línia i reiniciar el servei —sense
desplegar codi.

```bash
# Global
SAP_BACKEND=sql            # sql | sl

# Per funció (guanya sobre la global)
SAP_BACKEND_LLISTAR_CARREGUES=sl
```

Funcions commutables: `LLISTAR_CARREGUES`, `LLISTAR_ESTATS_CARREGUES`,
`LLISTAR_TRANSPORTISTES`, `CERCAR_ARTICLES`, `OBTENIR_DESCRIP_ARTICLES`,
`OBTENIR_COMANDES_CARREGA`, `RESUM_CARREGA`. La llista completa de variables és a
`deploy/env.production.example`.

`/health` diu quin backend serveix cada funció. Davant d'una incidència, és el
primer que s'ha de mirar:

```bash
curl -s http://127.0.0.1:50006/health | python3 -m json.tool
```

### 8.1 Abans de commutar res: l'arnès de paritat

```bash
cd /var/www/agrupacio-carregues-sap
sudo -u www-data venv/bin/python scripts/paritat_backends.py
```

Compara els dos backends sobre 259 casos i surt amb codi 1 si en troba cap
diferència. **Executar-ho al servidor**, perquè el camí de xarxa compta i perquè
els temps mesurats en una base de proves de 85 càrregues no extrapolen a
producció.

### 8.2 Els agregats del llistat

El llistat necessita `kg_total`, `num_comandes`, `palletitzable` i `is_granel`,
i el Service Layer **no els pot calcular**: no agrega ni filtra sobre línies de
document, i les línies no es poden retallar amb `$select` (vénen amb 247 camps,
~19 KB per comanda, i una pàgina són 500 càrregues). Es precalculen a PostgreSQL:

```bash
# Primera càrrega (o reconstrucció manual)
sudo systemctl start agrupacio-carregues-sap-agregats-complet

# Estat dels timers
systemctl list-timers 'agrupacio-carregues-sap-agregats*'
journalctl -u agrupacio-carregues-sap-agregats -n 20
```

Dos timers: incremental cada 2 minuts i reconstrucció completa a les 03:30.

**Conseqüència funcional:** aquests quatre camps del llistat i del calendari
porten fins a uns 2 minuts de retard. La fitxa de detall d'una càrrega
(`/api/carrega-detall`) segueix llegint en viu del Service Layer, així que en
obrir una càrrega les xifres són del moment.

Si el refrescador s'encalla, `/health` respon **503** amb `agregats.ok = false`.
És deliberat: el llistat seguiria responent amb dades velles i no se'n veuria res.

### 8.3 Marxa enrere

```bash
sudo nano /var/www/agrupacio-carregues-sap/.env   # SAP_BACKEND=sql
sudo systemctl restart agrupacio-carregues-sap
```

Hi ha també `SAP_BACKEND_FALLBACK=sql`, que reintenta per SQL si el Service Layer
falla. És útil els primers dies de cada commutació, però amaga els defectes del
backend nou: `/health` compta els cops que salta a `fallbacks_sql`. Desactivar-lo
quan ja no calgui.

### 8.4 El que encara llegeix per SQL

- **`/api/pbi/carregues`**, a propòsit: pagina fins a 5000 files i és consum
  màquina, no interactiu. L'import és explícit al codi, no configurable.
- **El motor d'embalatges** de `comandes-venda-sap`, que s'importa dins d'aquest
  procés i llegeix 10 taules per SQL. Per tant `pyodbc` i les credencials
  `SAP_SQL_*` segueixen fent falta, i `/api/agrupar` continua tocant SQL. Migrar
  aquell mòdul és un projecte propi, al seu repositori.
