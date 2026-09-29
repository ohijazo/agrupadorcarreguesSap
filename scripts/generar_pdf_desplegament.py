"""Genera el PDF de petició de desplegament per al departament de Sistemes.

Ús:
    python scripts/generar_pdf_desplegament.py

Sortida:
    docs/Desplegament_AgrupacioCarreguesSAP_Sistemes.pdf

Manté l'estil dels altres PDFs interns (vegeu generate_pdf.py de
preparacioComandesVendaSAP). Les fonts base de fpdf2 codifiquen en latin-1:
els accents catalans i el punt volat hi caben, però NO les fletxes unicode,
els guions llargs ni les cometes tipogràfiques.
"""
import os
import subprocess
import sys

from fpdf import FPDF

# --- Dades del desplegament ------------------------------------------------
APP_NAME = "Agrupador de Càrregues (variant SAP B1)"
APP_DIR = "/var/www/agrupacio-carregues-sap"
SERVICE_NAME = "agrupacio-carregues-sap"
APP_PORT = "50005"
SERVER_NAME = "agrupacions-sap.agrienergia.local"
SERVER_HOST = "ae01farwebsrv.agrienergia.local (192.168.11.244)"
GITHUB_REPO = "https://github.com/ohijazo/agrupadorcarreguesSap.git"
PG_DB = "agrupaciocarregues_sap"
PG_USER = "app_agrupacions_sap"
SOLICITANT = "Oscar Hijazo (ohijazo@agrienergia.com)"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "docs", "Desplegament_AgrupacioCarreguesSAP_Sistemes.pdf")


def _commit_actual() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "desconegut"


class GuiaPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 8, f"Petició de desplegament - {APP_NAME}", align="C")
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Pàgina {self.page_no()}/{{nb}}", align="C")

    def section_title(self, num, title):
        self.set_x(10)
        if self.get_y() > self.h - 45:
            self.add_page()
        self.ln(2)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(43, 108, 176)
        self.cell(0, 10, f"{num}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(43, 108, 176)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_x(10)
        if self.get_y() > self.h - 35:
            self.add_page()
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(45, 55, 72)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_x(10)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(26, 32, 44)
        self.multi_cell(0, 5.5, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def bullets(self, items):
        self.set_x(10)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(26, 32, 44)
        for it in items:
            if self.get_y() > self.h - 25:
                self.add_page()
            self.set_x(10)
            self.cell(5, 5.5, "-")
            self.multi_cell(self.w - 20 - 5, 5.5, it, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def code_block(self, text):
        self.set_font("Courier", "", 8.5)
        lines = text.split("\n")
        x = 10
        w = self.w - 20
        h = len(lines) * 4.6 + 6
        if self.get_y() + h > self.h - 20:
            self.add_page()
        self.set_fill_color(26, 32, 44)
        self.rect(x, self.get_y(), w, h, "F")
        self.set_text_color(226, 232, 240)
        self.set_xy(x + 3, self.get_y() + 3)
        for line in lines:
            self.cell(0, 4.6, line, new_x="LMARGIN", new_y="NEXT")
            self.set_x(x + 3)
        self.set_xy(x, self.get_y() + 3)
        self.set_text_color(26, 32, 44)
        self.ln(3)

    def info_box(self, text, box_type="info"):
        palette = {
            "info": ((235, 248, 255), (49, 130, 206)),
            "warning": ((255, 251, 235), (180, 130, 30)),
            "danger": ((255, 245, 245), (197, 48, 48)),
            "success": ((240, 255, 244), (47, 133, 90)),
        }
        bg, border = palette.get(box_type, palette["info"])
        x = 10
        w = self.w - 20
        self.set_font("Helvetica", "", 9)
        lines = self.multi_cell(w - 10, 5, text, dry_run=True, output="LINES")
        h = len(lines) * 5 + 8
        if self.get_y() + h > self.h - 20:
            self.add_page()
        y = self.get_y()
        self.set_fill_color(*bg)
        self.set_draw_color(*border)
        self.rect(x, y, w, h, "F")
        self.set_line_width(1)
        self.line(x, y, x, y + h)
        self.set_line_width(0.2)
        self.set_xy(x + 5, y + 4)
        self.set_text_color(*border)
        self.multi_cell(w - 10, 5, text, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(26, 32, 44)
        self.set_xy(x, y + h + 2)
        self.ln(2)

    def table(self, headers, rows, col_widths):
        self.set_x(10)
        if self.get_y() + 7 * (len(rows) + 1) > self.h - 20:
            self.add_page()
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(237, 242, 247)
        self.set_text_color(45, 55, 72)
        self.set_draw_color(203, 213, 224)
        for i, hd in enumerate(headers):
            self.cell(col_widths[i], 7, hd, border=1, fill=True)
        self.ln()
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(26, 32, 44)
        for row in rows:
            self.set_x(10)
            if self.get_y() + 6.5 > self.h - 20:
                self.add_page()
                self.set_x(10)
                self.set_font("Helvetica", "B", 9)
                self.set_fill_color(237, 242, 247)
                for i, hd in enumerate(headers):
                    self.cell(col_widths[i], 7, hd, border=1, fill=True)
                self.ln()
                self.set_x(10)
                self.set_font("Helvetica", "", 8.5)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6.5, str(cell), border=1)
            self.ln()
        self.ln(3)


def generate():
    commit = _commit_actual()
    pdf = GuiaPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # ---------------- Portada ----------------
    pdf.ln(18)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(26, 32, 44)
    pdf.multi_cell(0, 10, "Petició de desplegament", align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 15)
    pdf.set_text_color(74, 85, 104)
    pdf.multi_cell(0, 8, "Agrupador de Càrregues - variant SAP B1", align="C",
                   new_x="LMARGIN", new_y="NEXT")
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
            ["Servidor", SERVER_HOST],
            ["Plataforma", "Ubuntu Server 24.04 LTS"],
            ["Versió a desplegar", f"branca main, commit {commit}"],
            ["Temps estimat", "30-45 minuts"],
            ["Requereix reinici del servidor", "No"],
            ["Afecta la producció actual", "No (instal·lació en paral·lel)"],
        ],
        [60, 130],
    )

    pdf.ln(2)
    pdf.info_box(
        "RESUM: cal instal·lar una segona instància de l'Agrupador de Càrregues al "
        "mateix servidor web on ja corre l'actual. La instància nova llegeix de SAP "
        "B1 en lloc de Kais. Les dues han de conviure: la que ja hi ha NO s'ha de "
        "tocar ni aturar en cap moment.\n\n"
        "Tot el procés està automatitzat en un script (deploy.sh) dins del propi "
        "repositori. Sistemes només l'ha d'executar i donar d'alta una entrada DNS.",
        "info",
    )

    pdf.info_box(
        "NO TOCAR: /var/www/agrupacio-carregues, el servei agrupacio-carregues, el "
        "port 50004, la base de dades agrupaciocarregues ni el VirtualHost "
        "agrupacions.agrienergia.local. Són de la instància en producció.",
        "danger",
    )

    # ---------------- 1. Que es demana ----------------
    pdf.add_page()
    pdf.section_title(1, "Què es demana")
    pdf.body_text(
        "Desplegar una segona instància de l'aplicació Agrupador de Càrregues al "
        "servidor web intern. L'aplicació és la mateixa que ja fan servir oficina i "
        "magatzem, però aquesta variant llegeix les ordres de càrrega de SAP Business "
        "One en lloc de l'ERP Kais. Durant el període de convivència dels dos ERP, "
        "les dues instàncies han de funcionar alhora."
    )
    pdf.body_text("Recursos que cal crear al servidor:")
    pdf.bullets([
        f"Directori d'aplicació: {APP_DIR}",
        f"Servei systemd: {SERVICE_NAME} (Gunicorn escoltant a 127.0.0.1:{APP_PORT})",
        f"Base de dades PostgreSQL local: {PG_DB}, amb l'usuari {PG_USER}",
        f"VirtualHost d'Apache: {SERVER_NAME}",
        "Entrada al DNS corporatiu (l'únic pas que no fa l'script)",
    ])

    pdf.sub_title("1.1 Convivència amb la instància actual")
    pdf.table(
        ["Recurs", "Instància actual (Kais)", "Instància nova (SAP)"],
        [
            ["Directori", "/var/www/agrupacio-carregues", APP_DIR],
            ["Servei systemd", "agrupacio-carregues", SERVICE_NAME],
            ["Port intern", "50004", APP_PORT],
            ["URL", "agrupacions.agrienergia.local", SERVER_NAME],
            ["Base de dades", "agrupaciocarregues", PG_DB],
            ["Usuari PostgreSQL", "app_agrupacions", PG_USER],
            ["Origen de dades", "SQL Server vkais:50058", "SQL Server AE01SAPSQL:1433"],
        ],
        [34, 78, 78],
    )
    pdf.body_text(
        "Les dues bases de dades són separades expressament: els identificadors de "
        "càrrega de Kais i de SAP no són compatibles i barrejar-los corrompria les "
        "dades. No s'han d'unificar."
    )

    # ---------------- 2. Prerequisits ----------------
    pdf.section_title(2, "Prerequisits a verificar")
    pdf.body_text(
        "Abans d'executar l'script, comprovar aquests tres punts. L'script també els "
        "verifica i s'atura sense modificar res si algun falla."
    )

    pdf.sub_title("2.1 Aplicació germana SAP instal·lada")
    pdf.body_text(
        "Aquesta aplicació importa el mòdul de càlcul d'embalatges (motor.py) de "
        "l'aplicació Preparació de Comandes de Venda, variant SAP. Ha d'estar ja "
        "desplegada a /var/www/comandes-venda-sap."
    )
    pdf.code_block(
        "ls /var/www/comandes-venda-sap/motor.py\n"
        "grep KAIS_APP_PATH /var/www/comandes-venda-sap/.env\n"
        "# ha de retornar: KAIS_APP_PATH=/var/www/comandes-venda"
    )
    pdf.info_box(
        "Si /var/www/comandes-venda-sap no existeix, cal desplegar primer aquella "
        "aplicació (repositori PreparacioComandesVendaSAP, amb el seu propi "
        "deploy.sh --first-install) i després tornar aquí.",
        "warning",
    )

    pdf.sub_title("2.2 Connectivitat cap al SQL Server de SAP")
    pdf.code_block(
        "nc -zv AE01SAPSQL.Agrienergia.local 1433\n"
        "# ha de dir: succeeded / open"
    )
    pdf.body_text(
        "Si el port està tancat, cal obrir-lo al tallafocs del servidor SQL cap a "
        "192.168.11.244. L'aplicació hi accedeix només en lectura."
    )

    pdf.sub_title("2.3 Driver ODBC de SQL Server")
    pdf.body_text(
        "Cal el Microsoft ODBC Driver 18 for SQL Server. Ja hi hauria de ser, perquè "
        "la instància actual el fa servir; si no hi és, l'script l'instal·la."
    )
    pdf.code_block("odbcinst -q -d")

    # ---------------- 3. Recursos de xarxa ----------------
    pdf.section_title(3, "Recursos de xarxa a donar d'alta")
    pdf.sub_title("3.1 Entrada DNS (l'única acció manual fora del servidor)")
    pdf.table(
        ["Nom", "Tipus", "Valor"],
        [[SERVER_NAME, "CNAME", "ae01farwebsrv.agrienergia.local"]],
        [70, 25, 95],
    )
    pdf.body_text(
        "Es pot fer abans o després de la instal·lació. Fins que no existeixi, "
        "l'aplicació només es podrà provar des del mateix servidor."
    )

    pdf.sub_title("3.2 Ports")
    pdf.table(
        ["Port", "Abast", "Ús"],
        [
            ["80", "LAN (ja obert)", "Apache, proxy invers"],
            [APP_PORT, "només localhost", "Gunicorn de la instància nova"],
            ["5432", "només localhost", "PostgreSQL"],
            ["1433", "sortint cap a AE01SAPSQL", "Lectura de dades de SAP B1"],
        ],
        [22, 58, 110],
    )
    pdf.body_text(
        "No cal obrir cap port nou al tallafocs perimetral: el 50005 només escolta a "
        "127.0.0.1 i l'accés des de la xarxa passa sempre per Apache al port 80."
    )

    # ---------------- 4. Procediment ----------------
    pdf.section_title(4, "Procediment d'instal·lació")
    pdf.body_text(f"Executar al servidor {SERVER_HOST} amb un usuari amb sudo:")
    pdf.code_block(
        "cd /tmp\n"
        f"git clone {GITHUB_REPO} agrup-sap-tmp\n"
        "sudo bash agrup-sap-tmp/deploy.sh --first-install"
    )
    pdf.body_text("L'script fa, en aquest ordre:")
    pdf.bullets([
        "Verifica els prerequisits del punt 2 i s'atura si en falta algun.",
        "Instal·la els paquets del sistema i, si cal, el driver ODBC.",
        f"Clona el repositori a {APP_DIR}.",
        "Crea l'entorn virtual de Python i instal·la les dependències, incloses les "
        "de l'aplicació germana, que fan falta per al càlcul d'embalatges.",
        f"Crea l'usuari i la base de dades PostgreSQL ({PG_DB}) amb una contrasenya "
        "generada aleatòriament, i hi carrega l'esquema i les migracions.",
        "Genera el fitxer de configuració .env amb permisos 600.",
        "Instal·la la rotació de logs, el servei systemd i el VirtualHost d'Apache.",
    ])
    pdf.info_box(
        "L'script NO arrenca el servei al final, expressament: abans cal posar-hi les "
        "credencials de SAP (punt 5). Tampoc no toca cap fitxer ni cap servei de la "
        "instància actual.",
        "info",
    )

    # ---------------- 5. Configuracio ----------------
    pdf.section_title(5, "Configuració posterior i arrencada")
    pdf.sub_title("5.1 Credencials de SAP")
    pdf.body_text(
        "Editar el fitxer de configuració i substituir els valors marcats com a "
        "CANVIA_AQUESTA_CONTRASENYA per les credencials reals de l'usuari de lectura "
        "de SAP B1. Les facilita el sol·licitant."
    )
    pdf.code_block(f"sudo nano {APP_DIR}/.env")
    pdf.info_box(
        "Si alguna contrasenya conté espais o el caràcter #, cal posar-la entre "
        "cometes simples (per exemple SQL_PASSWORD='clau#amb coses'). El systemd "
        "llegeix aquest fitxer i, sense cometes, tallaria el valor.",
        "warning",
    )

    pdf.sub_title("5.2 Arrencar el servei")
    pdf.code_block(
        f"sudo systemctl start {SERVICE_NAME}\n"
        f"sudo systemctl status {SERVICE_NAME}\n"
        "# esperat: active (running)"
    )

    pdf.sub_title("5.3 Crear el primer usuari administrador")
    pdf.body_text(
        "Aquest pas el pot fer Sistemes o el sol·licitant. Demana la contrasenya per "
        "teclat, de manera que no queda a l'historial."
    )
    pdf.code_block(
        f"cd {APP_DIR}\n"
        "sudo -u www-data venv/bin/python scripts/crear_admin.py \\\n"
        "     --username ohijazo@agrienergia.com --nom \"Oscar Hijazo\""
    )

    # ---------------- 6. Acceptacio ----------------
    pdf.section_title(6, "Verificació i acceptació")
    pdf.body_text(
        "El desplegament es dóna per bo quan aquestes quatre comprovacions passen."
    )
    pdf.sub_title("6.1 L'aplicació i les seves dependències responen")
    pdf.code_block(
        f"curl -s http://127.0.0.1:{APP_PORT}/health\n"
        '# esperat: {"db":{"ok":true},"motor":{"ok":true},'
        '"ok":true,"pg":{"ok":true}}'
    )
    pdf.body_text(
        "db = SQL Server de SAP, pg = PostgreSQL local, motor = mòdul d'embalatges. "
        "Si algun surt false, vegeu la taula de diagnòstic del punt 8."
    )

    pdf.sub_title("6.2 Apache serveix la instància nova")
    pdf.code_block(
        f"curl -sI -H 'Host: {SERVER_NAME}' http://127.0.0.1/ | head -1\n"
        "# esperat: HTTP/1.1 302 FOUND (redirecció cap a /login)"
    )

    pdf.sub_title("6.3 La instància actual segueix intacta")
    pdf.code_block(
        "systemctl is-active agrupacio-carregues\n"
        "curl -s http://agrupacions.agrienergia.local/health\n"
        "# esperat: active, i el health de sempre"
    )

    pdf.sub_title("6.4 Accés des d'un PC de la xarxa")
    pdf.body_text(
        f"Un cop creada l'entrada DNS, obrir http://{SERVER_NAME}/ des d'un PC "
        "qualsevol: ha de sortir la pantalla d'entrada amb el distintiu blau SAP."
    )

    # ---------------- 7. Manteniment ----------------
    pdf.section_title(7, "Manteniment posterior")
    pdf.sub_title("7.1 Actualitzacions")
    pdf.body_text(
        "Les actualitzacions es fan amb el mateix script, sense arguments. Baixa la "
        "versió nova, reaplica les migracions de base de dades si cal, reinicia el "
        "servei i comprova que respon."
    )
    pdf.code_block(f"sudo bash {APP_DIR}/deploy.sh")

    pdf.sub_title("7.2 Comandes d'operació")
    pdf.code_block(
        f"sudo systemctl restart {SERVICE_NAME}\n"
        f"sudo journalctl -u {SERVICE_NAME} -f\n"
        f"tail -f {APP_DIR}/error.log {APP_DIR}/agrupacio.log"
    )

    pdf.sub_title("7.3 Còpies de seguretat")
    pdf.body_text(
        f"Cal afegir la base de dades {PG_DB} al joc de còpies de PostgreSQL que ja "
        f"cobreix agrupaciocarregues. També convé guardar {APP_DIR}/.env, que conté "
        "credencials i no és al repositori. El codi no cal: és a GitHub."
    )
    pdf.code_block(f"sudo -u postgres pg_dump {PG_DB} > {PG_DB}_$(date +%F).sql")

    # ---------------- 8. Diagnostic ----------------
    pdf.section_title(8, "Diagnòstic ràpid")
    pdf.table(
        ["Símptoma", "Causa probable", "Acció"],
        [
            ["motor: false a /health", "Falta comandes-venda-sap",
             "Revisar el punt 2.1"],
            ["db: false a /health", "No arriba a AE01SAPSQL o credencials",
             "nc -zv AE01SAPSQL 1433"],
            ["pg: false a /health", "Contrasenya de PostgreSQL desincronitzada",
             "Revisar PG_PASSWORD al .env"],
            ["El servei no arrenca", "Error de configuració al .env",
             f"journalctl -u {SERVICE_NAME} -n 50"],
            ["404 en obrir una càrrega", "Falta AllowEncodedSlashes al vhost",
             "Revisar el fitxer del site"],
            ["502 des del navegador", "El servei està aturat",
             f"systemctl status {SERVICE_NAME}"],
        ],
        [50, 70, 70],
    )
    pdf.info_box(
        "Les URL de l'aplicació contenen identificadors amb barres (format "
        "2026/01/0002266) que viatgen codificats. Per això el VirtualHost porta "
        "AllowEncodedSlashes NoDecode i nocanon. Si algú els treu, l'aplicació "
        "respon 404 en obrir qualsevol càrrega.",
        "warning",
    )

    # ---------------- 9. Marxa enrere ----------------
    pdf.section_title(9, "Marxa enrere")
    pdf.body_text(
        "Si cal desfer el desplegament, aquests passos deixen el servidor com estava. "
        "No afecten en cap cas la instància actual."
    )
    pdf.code_block(
        f"sudo systemctl stop {SERVICE_NAME}\n"
        f"sudo systemctl disable {SERVICE_NAME}\n"
        f"sudo rm /etc/systemd/system/{SERVICE_NAME}.service\n"
        "sudo systemctl daemon-reload\n"
        f"sudo a2dissite {SERVICE_NAME}.conf && sudo systemctl reload apache2\n"
        f"sudo rm /etc/logrotate.d/{SERVICE_NAME}\n"
        f"sudo rm -rf {APP_DIR}\n"
        "# Opcional, esborra les dades de la instancia nova:\n"
        f"sudo -u postgres psql -c 'DROP DATABASE {PG_DB};'\n"
        f"sudo -u postgres psql -c 'DROP ROLE {PG_USER};'"
    )

    # ---------------- 10. Contacte ----------------
    pdf.section_title(10, "Documentació i contacte")
    pdf.body_text(
        "La guia tècnica completa és al mateix repositori, a "
        "docs/DESPLEGAMENT-SAP.md. Els fitxers de configuració que instal·la "
        "l'script són a la carpeta deploy/, de manera que qualsevol canvi hi queda "
        "versionat."
    )
    pdf.table(
        ["Concepte", "Valor"],
        [
            ["Repositori", GITHUB_REPO],
            ["Guia tècnica", "docs/DESPLEGAMENT-SAP.md"],
            ["Script", "deploy.sh (arrel del repositori)"],
            ["Sol·licitant", SOLICITANT],
        ],
        [45, 145],
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
