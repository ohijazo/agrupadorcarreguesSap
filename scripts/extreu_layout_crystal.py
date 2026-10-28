"""Extreu de SAP el Crystal (.rpt) per defecte d'un tipus de document.

SAP desa el fitxer sencer a `RDOC.Template`, i el layout per defecte de cada
tipus a `RTYP.DEFLT_REP`. Serveix per inspeccionar el report (parametres,
subinformes) abans de passar-lo pel servei `serveis/crystal-pdf`. Nomes
lectura.

Us:
    python scripts/extreu_layout_crystal.py              # albara (DLN2)
    python scripts/extreu_layout_crystal.py INV2 sortida/
"""
import os
import sys

import pyodbc

# --- Carrega .env ---
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

TIPUS = sys.argv[1] if len(sys.argv) > 1 else "DLN2"
DESTI = sys.argv[2] if len(sys.argv) > 2 else "."

CS = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={os.environ['SAP_SQL_SERVER']};DATABASE={os.environ['SAP_SQL_DATABASE']};"
    f"UID={os.environ['SAP_SQL_USER']};PWD={os.environ['SAP_SQL_PASSWORD']};"
    f"TrustServerCertificate=yes;ApplicationIntent=ReadOnly;APP=ExtreuLayoutCrystal;"
)

cur = pyodbc.connect(CS, timeout=15, autocommit=True).cursor()
fila = cur.execute(
    "SELECT d.DocCode, d.DocName, d.UpdateDate, d.Template "
    "FROM RTYP t JOIN RDOC d ON d.DocCode = t.DEFLT_REP WHERE t.CODE = ?",
    TIPUS,
).fetchone()
if fila is None:
    sys.exit(f"No hi ha layout per defecte per al tipus {TIPUS}")
if fila.Template is None:
    sys.exit(f"{fila.DocCode} ({fila.DocName}) no te Template: es un layout del sistema (PLD)")

os.makedirs(DESTI, exist_ok=True)
cami = os.path.join(DESTI, f"{fila.DocCode}.rpt")
with open(cami, "wb") as f:
    f.write(fila.Template)
print(f"{fila.DocCode} '{fila.DocName}' (actualitzat {fila.UpdateDate:%Y-%m-%d}) "
      f"-> {cami} ({len(fila.Template)} bytes)")
