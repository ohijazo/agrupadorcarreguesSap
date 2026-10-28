"""Genera el PDF per a Sistemes amb la instal·lació del servei crystal-pdf al
servidor de SAP (impressió d'albarans amb el Crystal de SAP).

Ús:
    python scripts/generar_pdf_crystal_pdf.py

Sortida:
    docs/Instalacio_ServeiCrystalPdf_Sistemes.pdf

Reutilitza l'estil de `generar_pdf_desplegament.py`. Mateixa limitació: les
fonts base de fpdf2 són latin-1, així que res de fletxes, guions llargs ni
cometes tipogràfiques. Les línies de codi han de tenir menys de ~95 caràcters
perquè `code_block` no les parteix.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generar_pdf_desplegament import GuiaPDF, SOLICITANT, GITHUB_REPO, _commit_actual  # noqa: E402

TITOL = "Servei crystal-pdf (impressió d'albarans)"
SAP_HOST = "AE01SAPSQL.Agrienergia.local (192.168.11.238)"
WEB_HOST = "ae01farwebsrv.agrienergia.local (192.168.11.244)"
WEB_IP = "192.168.11.244"
APP_DIR = "/var/www/agrupacio-carregues-sap"
APP_SERVICE = "agrupacio-carregues-sap"
DIR = r"C:\Serveis\CrystalPdf"
PORT = "8095"
COMPTE = r"NT SERVICE\CrystalPdf"
BD = "DB_FARIN_TEST"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "docs", "Instalacio_ServeiCrystalPdf_Sistemes.pdf")


class Pdf(GuiaPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 8, f"Petició d'instal·lació - {TITOL}", align="C")
            self.ln(10)


def generate():
    commit = _commit_actual()
    pdf = Pdf()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ---------------- Portada ----------------
    pdf.ln(18)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(26, 32, 44)
    pdf.multi_cell(0, 10, "Petició d'instal·lació", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 15)
    pdf.set_text_color(74, 85, 104)
    pdf.multi_cell(0, 8, "Servei crystal-pdf al servidor de SAP\n(impressió d'albarans des de "
                   "l'Agrupador de Càrregues)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_draw_color(43, 108, 176)
    pdf.set_line_width(0.8)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(10)

    pdf.table(
        ["Camp", "Valor"],
        [
            ["Destinatari", "Departament de Sistemes"],
            ["Sol·licitant", SOLICITANT],
            ["Servidor on s'instal·la", SAP_HOST],
            ["Plataforma", "Windows Server, servei Windows (.NET Framework 4.8)"],
            ["Altres servidors implicats", f"{WEB_HOST}: només .env"],
            ["Versió", f"branca main, commit {commit}"],
            ["Temps estimat", "30 minuts"],
            ["Requereix reinici", "No (ni del servidor ni de SAP ni de SQL Server)"],
            ["Programari a instal·lar", "Cap: el servidor ja té tot el necessari"],
        ],
        [60, 130],
    )

    pdf.ln(2)
    pdf.info_box(
        "RESUM: l'Agrupador de Càrregues (Ubuntu) ha de poder imprimir els albarans "
        "exactament com els imprimeix SAP. Crystal Reports només funciona a Windows, així "
        "que cal instal·lar al servidor de SAP un petit servei Windows (crystal-pdf.exe) "
        "que genera el PDF amb el mateix layout de SAP. L'aplicació web li demana el PDF "
        f"pel port {PORT} i el mostra a l'usuari.",
        "info",
    )
    pdf.info_box(
        "SEGURETAT: el servei no té cap contrasenya en fitxers. Entra a SQL Server amb "
        f"el seu propi compte de Windows ({COMPTE}) i només amb permís de lectura. "
        "L'únic secret (un token compartit amb l'aplicació web) queda xifrat amb DPAPI de "
        f"la màquina. El port {PORT} només s'obre per al servidor web. El servei no "
        "desa cap PDF al disc.",
        "success",
    )

    # ---------------- 1. Que es demana ----------------
    pdf.add_page()
    pdf.section_title(1, "Què es demana")
    pdf.bullets([
        f"Al servidor de SAP: copiar crystal-pdf.exe a {DIR}, instal·lar-lo com a servei "
        f"Windows amb el compte virtual {COMPTE} i obrir el port {PORT} només per a "
        f"{WEB_IP}.",
        f"A SQL Server: donar a {COMPTE} permís de lectura (db_datareader) a {BD}.",
        f"Al servidor web: afegir dues línies al .env de l'aplicació i reiniciar-la.",
    ])

    pdf.sub_title("1.1 Com funciona")
    pdf.code_block(
        "Tablet / PC  -->  Agrupador (ae01farwebsrv, Ubuntu)\n"
        f"                     |  GET http://AE01SAPSQL:{PORT}/pdf?tipus=DLN2&docentry=N\n"
        "                     |  (capçalera X-Token)\n"
        f"                     v\n"
        f"              crystal-pdf (servidor de SAP, servei Windows, port {PORT})\n"
        "                     |  llegeix el layout de SAP (RDOC) i les dades de l'albarà\n"
        "                     v\n"
        f"              SQL Server local, BD {BD} (només lectura)"
    )
    pdf.body_text(
        "A cada petició el servei llegeix de SAP el layout per defecte dels albarans "
        "(ara DLN20014 \"ALBARÀ IVA-NOIVA COPIES\") i el genera amb el runtime de Crystal "
        "que ja hi ha instal·lat. Si es canvia el layout a SAP, el PDF canvia sol."
    )

    pdf.sub_title("1.2 Impacte al servidor de SAP")
    pdf.bullets([
        "Màxim 2 PDF simultanis (configurable). Cada albarà triga 1-6 segons de CPU.",
        "Ús de disc: només el layout vigent (uns 300 KB) i un log mensual.",
        "No modifica res de SAP ni de SQL Server: només hi llegeix.",
        "No s'instal·la ni s'actualitza cap programari.",
    ])

    # ---------------- 2. Prerequisits ----------------
    pdf.section_title(2, "Prerequisits (ja comprovats el 28-10-2026)")
    pdf.table(
        ["Requisit", "Estat al servidor de SAP"],
        [
            ["SAP Crystal Reports runtime for .NET (64 bits)", "Instal·lat: 13.0.38.5404"],
            ["Microsoft OLE DB Driver for SQL Server", "Instal·lat: MSOLEDBSQL i MSOLEDBSQL19"],
            [".NET Framework 4.8", "Instal·lat"],
            [f"Port {PORT} lliure", "Pendent de comprovar (ordre de sota)"],
        ],
        [95, 95],
    )
    pdf.code_block(
        f"Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue\n"
        "# si no retorna res, el port és lliure"
    )
    pdf.info_box(
        f"Si el {PORT} està ocupat, es pot fer servir qualsevol altre port: s'ha de "
        "canviar a la configuració del servei (Port), a la reserva d'URL i al tallafocs "
        "(punts 3.3 i 3.6) i a CRYSTAL_PDF_URL (punt 4).",
        "warning",
    )

    # ---------------- 3. Instal·lacio ----------------
    pdf.section_title(3, "Instal·lació al servidor de SAP")
    pdf.body_text("Tot en un PowerShell obert com a administrador.")

    pdf.sub_title("3.1 Copiar els fitxers")
    pdf.body_text(
        "El sol·licitant facilita crystal-pdf.exe i crystal-pdf.exe.config.example "
        "(també són al repositori, carpeta serveis/crystal-pdf; l'exe es pot compilar al "
        "mateix servidor amb build.cmd)."
    )
    pdf.code_block(
        f"New-Item -ItemType Directory -Force {DIR}\n"
        f"Copy-Item <origen>\\crystal-pdf.exe {DIR}\\\n"
        f"Copy-Item <origen>\\crystal-pdf.exe.config.example `\n"
        f"          {DIR}\\crystal-pdf.exe.config"
    )
    pdf.info_box(
        f"Si a {DIR} ja hi ha fitxers d'una prova anterior, es poden substituir. El "
        "crystal-pdf.exe.config de la prova pot contenir un usuari i una contrasenya de "
        "SQL: s'ha de substituir per la plantilla nova.",
        "warning",
    )

    pdf.sub_title("3.2 Crear el servei amb el seu compte virtual (sense arrencar-lo)")
    pdf.code_block(
        f'sc.exe create CrystalPdf binPath= "{DIR}\\crystal-pdf.exe" start= auto `\n'
        f'       obj= "{COMPTE}" DisplayName= "Crystal PDF (Agrupacio Carregues)"\n'
        "sc.exe description CrystalPdf \"PDF d'albarans amb el Crystal de SAP per a "
        "l'Agrupador\"\n"
        "sc.exe failure CrystalPdf reset= 86400 actions= restart/5000/restart/5000/restart/60000"
    )
    pdf.body_text(
        f"{COMPTE} és un compte virtual: Windows el crea sol amb el servei, no té "
        "contrasenya i no es pot fer servir per iniciar sessió."
    )

    pdf.sub_title("3.3 Permisos del compte del servei")
    pdf.code_block(
        f'icacls {DIR} /grant "{COMPTE}:(OI)(CI)M"\n'
        f'netsh http add urlacl url=http://+:{PORT}/ user="{COMPTE}"'
    )
    pdf.body_text(
        "El primer permet escriure a la seva carpeta (subcarpetes logs i treball). El "
        f"segon li permet escoltar al port {PORT} sense ser administrador."
    )

    pdf.sub_title("3.4 Accés de només lectura a SQL Server (SSMS)")
    pdf.code_block(
        f"CREATE LOGIN [{COMPTE}] FROM WINDOWS;\n"
        f"USE {BD};\n"
        f"CREATE USER [{COMPTE}] FOR LOGIN [{COMPTE}];\n"
        f"ALTER ROLE db_datareader ADD MEMBER [{COMPTE}];"
    )
    pdf.info_box(
        f"{BD} és la base de dades que fa servir avui l'Agrupador. Quan l'aplicació "
        "passi a la companyia real, caldrà repetir el USE / CREATE USER / ALTER ROLE "
        "sobre aquella base de dades (punt 6.3).",
        "info",
    )

    pdf.sub_title("3.5 Configurar i xifrar")
    pdf.body_text("Generar el token (copiar el resultat, es fa servir aquí i al punt 4):")
    pdf.code_block("[Convert]::ToBase64String((1..32 | % {Get-Random -Max 256}) -as [byte[]])")
    pdf.body_text(f"Editar {DIR}\\crystal-pdf.exe.config i deixar:")
    pdf.table(
        ["Clau", "Valor"],
        [
            ["Port", PORT],
            ["Escolta", "+"],
            ["Token", "el valor generat"],
            ["SqlServer", "localhost"],
            ["SqlDatabase", BD],
            ["SqlUser / SqlPassword", "BUITS (seguretat integrada)"],
            ["MaxJobs", "2"],
        ],
        [60, 130],
    )
    pdf.body_text("Xifrar la configuració (només es podrà llegir en aquest servidor):")
    pdf.code_block(
        f"{DIR}\\crystal-pdf.exe --protegeix\n"
        "# Per tornar-la a editar: --desprotegeix, editar, i --protegeix de nou"
    )

    pdf.sub_title("3.6 Arrencar i obrir el port només per al servidor web")
    pdf.code_block(
        "sc.exe start CrystalPdf\n"
        f"New-NetFirewallRule -DisplayName \"CrystalPdf {PORT}\" -Direction Inbound `\n"
        f"    -Protocol TCP -LocalPort {PORT} -RemoteAddress {WEB_IP} -Action Allow\n"
        f"Invoke-WebRequest http://localhost:{PORT}/health -UseBasicParsing | % Content\n"
        "# esperat: ok"
    )

    # ---------------- 4. Servidor web ----------------
    pdf.section_title(4, "Configuració al servidor web")
    pdf.body_text(f"Al servidor {WEB_HOST}, afegir al final del .env de l'aplicació:")
    pdf.code_block(
        f"sudo nano {APP_DIR}/.env\n"
        "\n"
        f"CRYSTAL_PDF_URL=http://AE01SAPSQL.Agrienergia.local:{PORT}\n"
        "CRYSTAL_PDF_TOKEN=<el mateix token del punt 3.5>"
    )
    pdf.code_block(f"sudo systemctl restart {APP_SERVICE}")
    pdf.info_box(
        "Si el token conté el caràcter # o espais, cal posar-lo entre cometes simples. "
        "Mentre CRYSTAL_PDF_URL és buit, la funció queda apagada a l'aplicació i no surt "
        "res als usuaris.",
        "warning",
    )

    # ---------------- 5. Verificacio ----------------
    pdf.section_title(5, "Verificació i acceptació")
    pdf.sub_title("5.1 El servidor web arriba al servei")
    pdf.code_block(
        f"curl -s http://AE01SAPSQL.Agrienergia.local:{PORT}/health\n"
        "# esperat: ok"
    )
    pdf.sub_title("5.2 Genera un albarà de prova (des del servidor web)")
    pdf.code_block(
        f"TOKEN=$(sudo grep ^CRYSTAL_PDF_TOKEN= {APP_DIR}/.env | cut -d= -f2- | tr -d \"'\")\n"
        f"curl -s -H \"X-Token: $TOKEN\" -o /tmp/albara_148.pdf -w '%{{http_code}}\\n' \\\n"
        f"  \"http://AE01SAPSQL.Agrienergia.local:{PORT}/pdf?tipus=DLN2&docentry=148\"\n"
        "file /tmp/albara_148.pdf && rm /tmp/albara_148.pdf\n"
        "# esperat: 200 i 'PDF document'"
    )
    pdf.body_text(
        "El token es llegeix del .env perquè no quedi a l'historial de la shell. "
        "El 148 és un albarà de la base de dades de proves."
    )
    pdf.sub_title("5.3 Un altre equip NO hi arriba")
    pdf.body_text(
        f"Des de qualsevol PC de la xarxa, http://AE01SAPSQL:{PORT}/health no ha de "
        "respondre (el tallafocs només deixa passar el servidor web)."
    )
    pdf.sub_title("5.4 Prova d'usuari")
    pdf.body_text(
        "La fa el sol·licitant: a l'Agrupador, pantalla de preparació d'una agrupació, "
        "secció \"Albarans de SAP\", botó \"Albarà\", i comparar el PDF amb el de SAP."
    )

    # ---------------- 6. Manteniment ----------------
    pdf.section_title(6, "Manteniment")
    pdf.sub_title("6.1 Logs")
    pdf.body_text(
        f"{DIR}\\logs\\AAAA-MM.log: una línia per PDF generat (albarà, mida, temps, IP) i "
        "el detall de cada error. Un fitxer per mes."
    )
    pdf.sub_title("6.2 Actualitzar l'executable")
    pdf.code_block(
        "sc.exe stop CrystalPdf\n"
        f"Copy-Item <origen>\\crystal-pdf.exe {DIR}\\ -Force\n"
        "sc.exe start CrystalPdf"
    )
    pdf.sub_title("6.3 Passar a la companyia real")
    pdf.code_block(
        "-- SSMS: repetir el punt 3.4 amb USE <BD real>\n"
        f"{DIR}\\crystal-pdf.exe --desprotegeix\n"
        "# editar SqlDatabase\n"
        f"{DIR}\\crystal-pdf.exe --protegeix\n"
        "sc.exe stop CrystalPdf; sc.exe start CrystalPdf"
    )

    pdf.sub_title("6.4 Diagnòstic ràpid")
    pdf.table(
        ["Símptoma", "Causa probable", "Acció"],
        [
            ["El servei no arrenca", "Falta urlacl o config", "Visor d'esdeveniments / logs"],
            ["/health no respon des del web", "Tallafocs o port", "Revisar regla del punt 3.6"],
            ["Error 401 a la prova 5.2", "Token diferent", "Comparar config i .env"],
            ["Error 500 al log: login failed", "Falta el punt 3.4", "Revisar permisos SQL"],
            ["Error 503 a l'aplicació", "Servei aturat", "sc.exe query CrystalPdf"],
        ],
        [55, 55, 80],
    )

    # ---------------- 7. Marxa enrere ----------------
    pdf.section_title(7, "Marxa enrere")
    pdf.body_text("Deixa el servidor de SAP com estava. Primer, al servidor web:")
    pdf.code_block(
        f"# buidar CRYSTAL_PDF_URL al {APP_DIR}/.env\n"
        f"sudo systemctl restart {APP_SERVICE}"
    )
    pdf.body_text("Al servidor de SAP (PowerShell administrador):")
    pdf.code_block(
        "sc.exe stop CrystalPdf\n"
        "sc.exe delete CrystalPdf\n"
        f"netsh http delete urlacl url=http://+:{PORT}/\n"
        f"Remove-NetFirewallRule -DisplayName \"CrystalPdf {PORT}\"\n"
        f"Remove-Item -Recurse -Force {DIR}"
    )
    pdf.code_block(
        f"-- SSMS\nUSE {BD}; DROP USER [{COMPTE}];\nDROP LOGIN [{COMPTE}];"
    )

    # ---------------- 8. Contacte ----------------
    pdf.section_title(8, "Documentació i contacte")
    pdf.table(
        ["Concepte", "Valor"],
        [
            ["Repositori", GITHUB_REPO],
            ["Codi i guia del servei", "serveis/crystal-pdf (README.md)"],
            ["Configuració de l'aplicació", "docs/DESPLEGAMENT-SAP.md, apartat 9"],
            ["Sol·licitant", SOLICITANT],
        ],
        [55, 135],
    )

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pdf.output(OUT)
    return OUT


if __name__ == "__main__":
    try:
        path = generate()
    except Exception as e:  # pragma: no cover
        print(f"ERROR generant el PDF: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"OK - PDF generat: {path}")
