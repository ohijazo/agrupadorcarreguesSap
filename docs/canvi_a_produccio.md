# Canvi a SAP de producció (`DB_FARIN_TEST` → `DB_FARINERA`)

SAP entra en producció el **dilluns 23/11/2026**. Aquell mateix dia, a les
00:00, l'app de KAIS (`agrupacions.agrienergia.local`) comença a redirigir
sola cap a `agrupacions-sap.agrienergia.local`. Per tant, **abans que comenci el
torn del dilluns**, aquesta app ha de llegir de `DB_FARINERA`.

El canvi és només de configuració: el codi no porta cap base de dades fixada.
La base de dades es tria al `.env` amb tres variables:

| Variable | Per a què |
|---|---|
| `SAP_SQL_DATABASE` / `SQL_DATABASE` | Lectures per SQL (càrregues, comandes, articles...) |
| `SAP_SL_COMPANY` | Service Layer: lectures `sl` i **escriptura** (cancel·lar albarans) |

Les mateixes variables hi són al `.env` de l'app germana `comandes-venda-sap`,
de la qual aquesta app importa el motor i el client del Service Layer. **S'han de
canviar totes dues**, o cada app llegirà d'una base de dades diferent.

> Compte: amb `DB_FARINERA`, **cancel·lar un albarà des de l'app el cancel·la a
> SAP de debò**.

---

## Herència de KAIS: l'usuari no ha de notar el canvi

L'app SAP hereta de l'app de KAIS (`agrupacio-carregues`):

| Què | Com |
|---|---|
| **Usuaris** | Es creen els que no hi són, amb el mateix hash de contrasenya, rol i estat. Entren amb la contrasenya de sempre. |
| **Agrupacions** | Les dels últims tres mesos, amb els productes preparats i les càrregues. Conserven l'id. |
| **Càrregues del calendari** | Del 23/08/2026 al 22/11/2026, amb el detall de cadascuna, a la taula `historic_carregues` (migració 009). |

És una **còpia congelada**: a KAIS ja no s'hi fa res i l'app SAP no en depèn.
Es fa en dos passos:

1. `scripts/exportar_historic.py` de l'**app de KAIS**: llegeix KAIS i el seu
   PostgreSQL i escriu un JSON. Només llegeix.
2. `scripts/importar_historic_kais.py` d'**aquesta app**: ho desa a PostgreSQL.
   Es pot repetir sense duplicar res. Amb `--simular` ho desfà al final.

El calendari demana `historic=1` i hi barreja les càrregues de KAIS, igual que
les veia a KAIS: sense filtre d'estat i sense la columna de pistolejat. Els ids
no es poden confondre: els de SAP comencen per `SAP/` i els de KAIS per l'any.
Les agrupacions de KAIS no es sincronitzen amb el pistolejat de SAP.

---

## Automatització (servidor `ae01farwebsrv` i servidor de SAP)

Els passos 1-7 del dia, més l'herència, estan automatitzats:

| On | Script | Programat |
|---|---|---|
| Ubuntu | `deploy/canvi_produccio.sh` | timer systemd `agrupacio-canvi-produccio`, 23/11/2026 00:05 |
| Windows (SAP) | `serveis/crystal-pdf/canvi_produccio.ps1` | tasca programada, 23/11/2026 00:05, com a SYSTEM |

`canvi_produccio.sh` primer comprova que s'arriba a `DB_FARINERA` per SQL i pel
Service Layer. Si falla, no toca res. Si alguna cosa falla un cop començat,
torna els `.env` i PostgreSQL a l'estat d'abans. Si els `.env` ja apunten a
`DB_FARINERA`, no fa res.

```bash
cd /var/www/agrupacio-carregues-sap
sudo bash deploy/canvi_produccio.sh --comprovar   # assaig: no toca res
sudo bash deploy/canvi_produccio.sh --programar   # deixa el timer a punt
systemctl list-timers agrupacio-canvi-produccio.timer
# el dia 23: sudo journalctl -u agrupacio-canvi-produccio.service --no-pager
```

```powershell
# servidor de SAP, consola d'administrador
C:\Serveis\CrystalPdf\canvi_produccio.ps1             # assaig
C:\Serveis\CrystalPdf\canvi_produccio.ps1 -Programar  # tasca programada
# el dia 23: C:\Serveis\CrystalPdf\logs\canvi_produccio.log
```

---

## Estat (comprovat el 18/11/2026)

- Des del servidor s'arriba a `DB_FARINERA` (prova feta encara amb `sa`).
- Hi ha les **dades mestres**: `OITM` 2.072 articles, `OCRD` 5.749 clients
  (l'últim creat el 16/11).
- **Encara no hi ha operativa**: `ORDR` (comandes) i `ODLN` (entregues) són a 0.

Per això el canvi de base de dades **no es pot avançar**: amb `DB_FARINERA`
l'app no mostraria cap càrrega, i qui hi fa proves les perdria. S'ha de fer
quan es comencin a entrar comandes a SAP de producció (cap de setmana o dilluns
23 a primera hora). Cal que les comandes que es carreguen el dilluns s'entrin a
`DB_FARINERA`, no a KAIS ni a `DB_FARIN_TEST`: si no, l'app no les veu.

Per tornar-ho a comprovar (només llegeix):

```bash
sudo -u www-data /var/www/agrupacio-carregues-sap/venv/bin/python - <<'PY'
import pyodbc
env = {}
for l in open("/var/www/agrupacio-carregues-sap/.env"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1); env[k.strip()] = v.strip()
cs = ("DRIVER={ODBC Driver 18 for SQL Server};"
      f"SERVER={env['SAP_SQL_SERVER']};DATABASE=DB_FARINERA;"
      f"UID={env['SAP_SQL_USER']};PWD={env['SAP_SQL_PASSWORD']};"
      "TrustServerCertificate=yes;ApplicationIntent=ReadOnly;")
c = pyodbc.connect(cs, timeout=10).cursor()
for taula in ("ORDR", "ODLN", "OITM", "OCRD"):
    n, ult = c.execute(f"SELECT COUNT(*), MAX(CreateDate) FROM {taula}").fetchone()
    print(f"{taula:5} {n:>8} files   darrera creacio: {ult}")
PY
```

---

## Usuari SQL propi en lloc de `sa`

Fins al 18/11 les dues apps es connectaven a SQL Server com a `sa`, que és
l'administrador i pot escriure i esborrar a l'ERP. `ApplicationIntent=ReadOnly`
no ho impedeix: només encamina la connexió. Cap de les dues apps escriu a SAP
per SQL (les cancel·lacions van pel Service Layer i l'únic `INSERT` és a
PostgreSQL), així que n'hi ha prou amb un usuari de només lectura. Es fa abans
del canvi, contra `DB_FARIN_TEST`, i ja queda llest per a `DB_FARINERA`.

**1. Crear-lo** (a `AE01SAPSQL`, des de l'SSMS, amb un compte administrador).
Contrasenya llarga, p. ex. `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`:

```sql
CREATE LOGIN agrupacions_lectura
    WITH PASSWORD = '<contrasenya>',
         CHECK_POLICY = ON, CHECK_EXPIRATION = OFF;   -- que no caduqui i aturi l'app

USE DB_FARINERA;
CREATE USER agrupacions_lectura FOR LOGIN agrupacions_lectura;
ALTER ROLE db_datareader ADD MEMBER agrupacions_lectura;

USE DB_FARIN_TEST;
CREATE USER agrupacions_lectura FOR LOGIN agrupacions_lectura;
ALTER ROLE db_datareader ADD MEMBER agrupacions_lectura;
```

**2. Provar-lo des del servidor** abans de tocar cap `.env` (la contrasenya es
demana per pantalla i no queda a l'historial). Han de sortir dos `OK`:

```bash
sudo -u www-data /var/www/agrupacio-carregues-sap/venv/bin/python - <<'PY'
import getpass, pyodbc
pwd = getpass.getpass("Contrasenya d'agrupacions_lectura: ")
for bd in ("DB_FARIN_TEST", "DB_FARINERA"):
    try:
        c = pyodbc.connect("DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER=AE01SAPSQL.Agrienergia.local;DATABASE={bd};"
            f"UID=agrupacions_lectura;PWD={pwd};"
            "TrustServerCertificate=yes;ApplicationIntent=ReadOnly;", timeout=10).cursor()
        n, ult = c.execute("SELECT COUNT(*), MAX(CreateDate) FROM ODLN").fetchone()
        print(f"{bd:14} OK   entregues: {n}   darrera: {ult}")
    except Exception as e:
        print(f"{bd:14} ERROR  {e}")
PY
```

**3. Posar-lo als dos `.env`** i reiniciar:

```bash
D=$(date +%Y%m%d-%H%M)
sudo cp /var/www/agrupacio-carregues-sap/.env /root/agrupacio-sap.env.$D
sudo cp /var/www/comandes-venda-sap/.env      /root/comandes-sap.env.$D

sudo nano /var/www/agrupacio-carregues-sap/.env
#   SAP_SQL_USER=agrupacions_lectura   SAP_SQL_PASSWORD=<contrasenya>
#   SQL_USER=agrupacions_lectura       SQL_PASSWORD=<contrasenya>
sudo nano /var/www/comandes-venda-sap/.env
#   SAP_SQL_USER=agrupacions_lectura   SAP_SQL_PASSWORD=<contrasenya>

sudo grep -n 'SQL_USER' /var/www/agrupacio-carregues-sap/.env /var/www/comandes-venda-sap/.env
sudo systemctl restart comandes-venda-sap.service agrupacio-carregues-sap.service
curl -s http://127.0.0.1:50006/health
```

Obrir l'app i comprovar que surten les càrregues. Els timers (agregats,
pistolejat) llegeixen el mateix `.env` a cada passada: no cal reiniciar-los.
Per tornar enrere: copiar els `.env` de `/root/` i reiniciar els dos serveis.

---

## Abans del dia

- [ ] `DB_FARINERA` té comandes i entregues (vegeu «Estat» més amunt).
- [x] Les apps es connecten amb `agrupacions_lectura` i no amb `sa`
      (secció anterior). Fet el 18/11/2026: login creat a `DB_FARINERA` i
      `DB_FARIN_TEST`, els dos `.env` canviats i `/health` OK. Contrasenya al KeePass.
- [ ] Des del servidor s'hi arriba amb l'usuari SQL del `.env`.
      Es comprova amb `nc -zv AE01SAPSQL.Agrienergia.local 1433`, i amb el pas 6
      del dia, provat abans en una còpia del `.env`.
- [ ] L'usuari del Service Layer (`SAP_SL_USER`) pot entrar a la companyia
      `DB_FARINERA`. A producció els usuaris de SAP poden no ser els de proves.
      Recomanat: un usuari propi de l'app, i no el personal.
- [x] **crystal-pdf** (servidor de SAP, Windows) — fet el 18/11/2026, comprovat
      `db_datareader` + EXECUTE a les dues funcions. El compte del servei ha de
      poder llegir `DB_FARINERA` i executar les dues funcions escalars de SEIDOR
      que crida el layout `DLN20014` (sense EXECUTE, Crystal falla amb l'error
      229). Vegeu `serveis/crystal-pdf/README.md`, pas 4:
      ```sql
      USE DB_FARINERA;
      IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'NT SERVICE\CrystalPdf')
          CREATE USER [NT SERVICE\CrystalPdf] FOR LOGIN [NT SERVICE\CrystalPdf];
      ALTER ROLE db_datareader ADD MEMBER [NT SERVICE\CrystalPdf];
      GRANT EXECUTE ON dbo.SEI_MODIFICAR_CODI_IDIOMA TO [NT SERVICE\CrystalPdf];
      GRANT EXECUTE ON dbo.SEI_TRADUCCIO TO [NT SERVICE\CrystalPdf];
      ```

---

## El dia del canvi (servidor `ae01farwebsrv`)

Es pot fer quan `DB_FARINERA` estigui a punt, el cap de setmana del 21–22/11, o
el dilluns 23 abans del torn.

### 1. Còpies de seguretat

```bash
D=$(date +%Y%m%d-%H%M)
sudo cp /var/www/agrupacio-carregues-sap/.env /root/agrupacio-sap.env.$D
sudo cp /var/www/comandes-venda-sap/.env      /root/comandes-sap.env.$D
sudo -u postgres pg_dump -Fc agrupaciocarregues_sap > /root/agrupaciocarregues_sap.$D.dump
```

### 2. Aturar serveis i timers

```bash
sudo systemctl stop agrupacio-carregues-sap-agregats.timer \
                    agrupacio-carregues-sap-agregats-complet.timer \
                    agrupacio-carregues-sap-pistolejat.timer
sudo systemctl stop agrupacio-carregues-sap.service comandes-venda-sap.service
```

### 3. Apuntar els dos `.env` a producció

```bash
for f in /var/www/agrupacio-carregues-sap/.env /var/www/comandes-venda-sap/.env; do
    sudo sed -i 's/=DB_FARIN_TEST$/=DB_FARINERA/' "$f"
    echo "== $f"; sudo grep -n 'DB_FARIN' "$f"     # totes han de dir DB_FARINERA
done
```

Si canvien també l'usuari o la contrasenya (de SQL o del Service Layer), és el
moment d'editar-los: `sudo nano <fitxer>`.

### 4. Buidar les dades de proves de PostgreSQL

Les agrupacions, els agregats i les cancel·lacions que hi ha ara apunten a
càrregues de `DB_FARIN_TEST`, i a producció serien soroll o col·lisions
d'identificadors. **Els usuaris, l'auditoria i `meta_agrupacions` es conserven.**

```bash
sudo -u postgres psql -d agrupaciocarregues_sap <<'SQL'
BEGIN;
TRUNCATE agrupacions CASCADE;            -- també productes_preparats i agrupacio_carregues
TRUNCATE kais_carrega_snapshot, kais_carrega_override,
         ordre_carrega_cache, albarans_cancelats;
UPDATE agregats_meta SET ultim_refresc_complet = NULL, ultim_refresc_incr = NULL,
                         ultim_error = NULL, comandes = 0;
COMMIT;
SQL
```

### 5. Engegar i reconstruir els agregats

```bash
sudo systemctl start comandes-venda-sap.service agrupacio-carregues-sap.service
sudo -u www-data /var/www/agrupacio-carregues-sap/venv/bin/python \
     /var/www/agrupacio-carregues-sap/scripts/refrescar_agregats.py --complet
sudo systemctl start agrupacio-carregues-sap-agregats.timer \
                     agrupacio-carregues-sap-agregats-complet.timer \
                     agrupacio-carregues-sap-pistolejat.timer
```

### 6. Comprovar

```bash
sudo systemctl status agrupacio-carregues-sap.service comandes-venda-sap.service --no-pager
curl -s http://127.0.0.1:50006/health      # ok: true, motor ok, agregats recents
```

Obrir `http://agrupacions-sap.agrienergia.local/` i `/calendari`, i comprovar
que surten les càrregues reals de SAP: comparar-ne un parell amb el client de SAP.

### 7. crystal-pdf (servidor de SAP)

El `crystal-pdf.exe.config` està xifrat: s'ha de desxifrar, editar i tornar a
xifrar. En una consola d'administrador:

```powershell
C:\Serveis\CrystalPdf\crystal-pdf.exe --desprotegeix
notepad C:\Serveis\CrystalPdf\crystal-pdf.exe.config
#   <add key="SqlDatabase" value="DB_FARINERA" />
C:\Serveis\CrystalPdf\crystal-pdf.exe --protegeix
Restart-Service CrystalPdf
```

Al log (`C:\Serveis\CrystalPdf\logs\`) ha de sortir `Escoltant al port 8095 (BD DB_FARINERA)`.

Comprovar que s'imprimeix l'albarà d'una càrrega real des de l'app.

---

## Tornar enrere

```bash
sudo systemctl stop agrupacio-carregues-sap.service comandes-venda-sap.service
sudo cp /root/agrupacio-sap.env.<D> /var/www/agrupacio-carregues-sap/.env
sudo cp /root/comandes-sap.env.<D>  /var/www/comandes-venda-sap/.env
sudo -u postgres pg_restore --clean -d agrupaciocarregues_sap /root/agrupaciocarregues_sap.<D>.dump
sudo systemctl start comandes-venda-sap.service agrupacio-carregues-sap.service
```

Al crystal-pdf, tornar a posar `DB_FARIN_TEST` i reiniciar-lo.
