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

## Abans del dia

- [ ] `DB_FARINERA` té les dades de producció carregades.
- [ ] Des del servidor s'hi arriba amb l'usuari SQL del `.env`.
      Es comprova amb `nc -zv AE01SAPSQL.Agrienergia.local 1433`, i amb el pas 6
      del dia, provat abans en una còpia del `.env`.
- [ ] L'usuari del Service Layer (`SAP_SL_USER`) pot entrar a la companyia
      `DB_FARINERA`. A producció els usuaris de SAP poden no ser els de proves.
      Recomanat: un usuari propi de l'app, i no el personal.
- [ ] **crystal-pdf** (servidor de SAP, Windows): el compte del servei ha de
      poder llegir `DB_FARINERA`:
      ```sql
      USE DB_FARINERA;
      CREATE USER [NT SERVICE\CrystalPdf] FOR LOGIN [NT SERVICE\CrystalPdf];
      ALTER ROLE db_datareader ADD MEMBER [NT SERVICE\CrystalPdf];
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

A `C:\Serveis\CrystalPdf\crystal-pdf.exe.config`, posar
`<add key="SqlDatabase" value="DB_FARINERA" />` i reiniciar el servei:

```powershell
Restart-Service CrystalPdf
```

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
