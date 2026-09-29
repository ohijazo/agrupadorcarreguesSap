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
| Port intern (Gunicorn) | 50004 | **50005** |
| URL | `agrupacions.agrienergia.local` | **`agrupacions-sap.agrienergia.local`** |
| Base de dades PostgreSQL | `agrupaciocarregues` | **`agrupaciocarregues_sap`** |
| Usuari PostgreSQL | `app_agrupacions` | **`app_agrupacions_sap`** |
| Origen de dades | SQL Server `vkais:50058` | SQL Server `AE01SAPSQL` (`DB_FARINERA_TEST`) |
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
   grep KAIS_APP_PATH /var/www/comandes-venda-sap/.env   # ha de dir /var/www/comandes-venda
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

1. Comprova els prerequisits (app germana, Kais, `KAIS_APP_PATH`).
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
curl -s http://127.0.0.1:50005/health
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
- **No posis `KAIS_APP_PATH` al `.env` d'aquesta app.** `app.py` carrega el `.env`
  de `PREPARACIO_PATH` com a *fallback*, i és d'allà que ha de venir. Si el
  defineixes aquí, guanya el teu valor i pots trencar els imports de
  `models`/`regles`/`mailer`.
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
- **Port 50005**: el fixa el `systemd` (`Environment=PORT=50005`, després de
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
