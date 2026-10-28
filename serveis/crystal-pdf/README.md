# crystal-pdf: PDF dels documents de SAP amb el seu mateix Crystal

L'app d'Agrupació de Càrregues viu a Ubuntu i Crystal Reports només funciona a
Windows. Aquest servei corre al **servidor de SAP** i genera el PDF d'un document
amb el layout per defecte que hi ha configurat a SAP. Ara mateix és
`DLN20014 "ALBARÀ IVA-NOIVA COPIES"` per als albarans. El resultat és idèntic al que
imprimeix SAP B1.

```
Tablet/PC ─► App Flask (Ubuntu) ─► crystal-pdf (servidor SAP, port 8095) ─► SQL Server
```

## Com funciona cada petició
`GET /pdf?tipus=DLN2&docentry=148` amb la capçalera `X-Token`:

1. Comprova que el document existeix (`ODLN`). Si no hi és, retorna 404, no un PDF en blanc.
2. Llegeix de SAP el layout per defecte del tipus (`RTYP.DEFLT_REP`) i el `.rpt` sencer (`RDOC.Template`). Es llegeix cada vegada: si es canvia el layout a SAP, el PDF canvia sol.
3. Reapunta les taules del report i dels 4 subinformes a la BD configurada.
4. Posa `DocKey@` = docentry, igual que SAP.
5. Retorna el PDF. Afegeix la capçalera `X-DocNum`.

Altres endpoints: `GET /health` respon `ok`, sense token.

Respostes d'error: `400` paràmetres, `401` token, `404` document inexistent,
`503` massa PDF alhora, `500` error de Crystal (el detall queda a `logs\`).

## Requisits (el servidor de SAP ja els té, comprovat el 28-10-2026)
- SAP Crystal Reports runtime engine for .NET Framework **64 bits**. Hi ha la 13.0.38.
- Microsoft OLE DB Driver for SQL Server (`MSOLEDBSQL`), amb el qual està desat el report.
- .NET Framework 4.8.

## Compilar (a qualsevol PC amb el runtime de Crystal)
```
serveis\crystal-pdf\build.cmd
```
Deixa `bin\crystal-pdf.exe` i, el primer cop, una còpia de la configuració d'exemple.

## Instal·lar al servidor de SAP
En producció **no hi ha cap contrasenya en cap fitxer**:
- El servei corre amb el compte virtual de Windows `NT SERVICE\CrystalPdf`, i SQL Server el reconeix per seguretat integrada. No hi ha usuari ni contrasenya SQL.
- L'únic secret és el `Token`, i va xifrat amb DPAPI de la màquina (`--protegeix`). El fitxer només es pot desxifrar en aquest servidor.
- Els PDF no es desen enlloc. Es generen en memòria i s'envien directament.

Tot en un PowerShell com a administrador:

1. **Copiar els fitxers**
   ```powershell
   New-Item -ItemType Directory -Force C:\Serveis\CrystalPdf
   Copy-Item <origen>\crystal-pdf.exe C:\Serveis\CrystalPdf\
   Copy-Item <origen>\crystal-pdf.exe.config.example C:\Serveis\CrystalPdf\crystal-pdf.exe.config
   ```

2. **Crear el servei amb el seu compte virtual**, sense arrencar-lo encara
   ```powershell
   sc.exe create CrystalPdf binPath= "C:\Serveis\CrystalPdf\crystal-pdf.exe" start= auto obj= "NT SERVICE\CrystalPdf" DisplayName= "Crystal PDF (Agrupacio Carregues)"
   sc.exe failure CrystalPdf reset= 86400 actions= restart/5000/restart/5000/restart/60000
   ```

3. **Permisos per al compte del servei**:
   - escriure a la seva carpeta, per a `logs\` i `treball\`;
   - escoltar al port.
   ```powershell
   icacls C:\Serveis\CrystalPdf /grant "NT SERVICE\CrystalPdf:(OI)(CI)M"
   netsh http add urlacl url=http://+:8095/ user="NT SERVICE\CrystalPdf"
   ```

4. **Accés de només lectura a SQL**, a SSMS:
   ```sql
   CREATE LOGIN [NT SERVICE\CrystalPdf] FROM WINDOWS;
   USE DB_FARIN_TEST;   -- i, quan es passi a producció, la BD real
   CREATE USER [NT SERVICE\CrystalPdf] FOR LOGIN [NT SERVICE\CrystalPdf];
   ALTER ROLE db_datareader ADD MEMBER [NT SERVICE\CrystalPdf];
   ```

5. **Configurar i xifrar**. Al `crystal-pdf.exe.config`:
   - `Token`: generar-lo aquí mateix amb `[Convert]::ToBase64String((1..32 | % {Get-Random -Max 256}) -as [byte[]])`. Copiar-lo a `CRYSTAL_PDF_TOKEN` del `.env` de l'app.
   - `SqlServer` = `localhost`, `SqlDatabase` = `DB_FARIN_TEST`.
   - `SqlUser` i `SqlPassword` **buits**.

   Després:
   ```powershell
   C:\Serveis\CrystalPdf\crystal-pdf.exe --protegeix
   ```
   Per tornar a editar el fitxer: `--desprotegeix`, editar, i `--protegeix` un altre cop.

6. **Arrencar-lo i obrir el port només per al servidor web**
   ```powershell
   sc.exe start CrystalPdf
   New-NetFirewallRule -DisplayName "CrystalPdf 8095" -Direction Inbound -Protocol TCP `
     -LocalPort 8095 -RemoteAddress <IP de ae01farwebsrv> -Action Allow
   ```

7. **Comprovar-ho des de `ae01farwebsrv`**
   ```bash
   curl http://AE01SAPSQL:8095/health      # -> ok
   ```

### Prova a mà (opcional, abans del pas 2)
`crystal-pdf.exe --prova DLN2 148 C:\Temp\albara_148.pdf` genera un PDF amb l'usuari de Windows que l'executa.
- Si aquest usuari no té accés a SQL, es pot posar temporalment un `SqlUser`/`SqlPassword` de lectura al `.config`, però **s'ha de buidar en acabar**.
- El PDF de prova és l'únic fitxer que es desa, i és on s'indica. Es pot esborrar quan s'hagi comparat.

## Manteniment
- Log: `C:\Serveis\CrystalPdf\logs\AAAA-MM.log`. Hi ha una línia per PDF i el detall de cada error.
- `treball\` només guarda el `.rpt` vigent de cada layout, d'uns 300 KB. Les versions velles s'esborren soles quan canvia el layout a SAP. Es pot buidar en qualsevol moment.
- Crystal fa servir el `%TEMP%` del compte del servei mentre genera un PDF, i ho allibera en acabar cada document.
- Actualitzar l'exe: `sc.exe stop CrystalPdf`, substituir l'exe, `sc.exe start CrystalPdf`.
- Passar a producció: fer el pas 4 sobre la BD real, `--desprotegeix`, canviar `SqlDatabase`, `--protegeix` i reiniciar el servei.
