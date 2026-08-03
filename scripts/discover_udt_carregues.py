"""Discovery efímer: on estan les 'carregues' dins SAP B1 DB_FARINERA_TEST.

Enumera UDT (@...), UDF (U_...) i objectes candidats amb noms
relacionats amb 'carrega', 'carga', 'transport', 'shipping', 'expedic',
etc. Per a cada candidat, imprimeix columnes i unes files de mostra.

Ús:
    python scripts/discover_udt_carregues.py > udt_report.txt
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

SERVER = os.environ["SAP_SQL_SERVER"]
DATABASE = os.environ["SAP_SQL_DATABASE"]
USER = os.environ["SAP_SQL_USER"]
PASSWORD = os.environ["SAP_SQL_PASSWORD"]

CS = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={SERVER};DATABASE={DATABASE};UID={USER};PWD={PASSWORD};"
    f"TrustServerCertificate=yes;ApplicationIntent=ReadOnly;APP=DiscoveryUDT;"
)

print(f"[INFO] Connectant a {SERVER} / {DATABASE} ...", flush=True)
conn = pyodbc.connect(CS, timeout=15, autocommit=True)
cur = conn.cursor()

# Paraules clau per detectar taules/camps de càrregues.
KEYWORDS = ("carr", "carg", "transp", "ship", "exped", "deliv", "load", "route")


def _like_clauses(col: str) -> str:
    """Retorna una clàusula OR amb LIKE per cada keyword sobre `col`."""
    parts = [f"UPPER({col}) LIKE '%{kw.upper()}%'" for kw in KEYWORDS]
    return "(" + " OR ".join(parts) + ")"


# =============================================================================
# 1) UDT: totes les User Defined Tables (@...) — llista completa + les
#    candidates que continguin alguna paraula clau al nom o descripció.
# =============================================================================
print("\n\n============================================================")
print("1) UDT (User Defined Tables — OUTB)")
print("============================================================", flush=True)

cur.execute("""
    SELECT TableName, Descr, ObjectType
    FROM   OUTB
    ORDER  BY TableName
""")
udt_rows = cur.fetchall()
print(f"\n[INFO] Total UDT: {len(udt_rows)}")
print("\n--- Totes les UDT (nom + descripcio + tipus) ---")
for r in udt_rows:
    print(f"  @{r.TableName:40}  type={r.ObjectType}  descr={(r.Descr or '').strip()}")

udt_candidates: list[str] = []
for r in udt_rows:
    name = (r.TableName or "").upper()
    descr = (r.Descr or "").upper()
    if any(kw.upper() in name or kw.upper() in descr for kw in KEYWORDS):
        udt_candidates.append(r.TableName)

print(f"\n[INFO] UDT candidates (keyword match): {udt_candidates}")


# =============================================================================
# 2) UDF: camps U_ que continguin alguna paraula clau
# =============================================================================
print("\n\n============================================================")
print("2) UDF (User Defined Fields — CUFD)")
print("============================================================", flush=True)

cur.execute(f"""
    SELECT TableID, AliasID, Descr, TypeID, EditType, EditSize
    FROM   CUFD
    WHERE  {_like_clauses("AliasID")}
        OR {_like_clauses("Descr")}
        OR {_like_clauses("TableID")}
    ORDER  BY TableID, AliasID
""")
udf_rows = cur.fetchall()
print(f"\n[INFO] UDF candidates: {len(udf_rows)}")
for r in udf_rows:
    print(f"  {r.TableID:20} U_{r.AliasID:30}  type={r.TypeID}/{r.EditType}  size={r.EditSize}  descr={(r.Descr or '').strip()}")


# =============================================================================
# 3) Taules nadives SAP amb noms/descripcions relacionades amb transport/entrega
#    (a INFORMATION_SCHEMA.TABLES es veuen també les @... i les UDT internes)
# =============================================================================
print("\n\n============================================================")
print("3) INFORMATION_SCHEMA.TABLES amb keyword al nom")
print("============================================================", flush=True)

cur.execute(f"""
    SELECT TABLE_NAME, TABLE_TYPE
    FROM   INFORMATION_SCHEMA.TABLES
    WHERE  {_like_clauses("TABLE_NAME")}
    ORDER  BY TABLE_NAME
""")
for r in cur.fetchall():
    print(f"  {r.TABLE_NAME:40}  {r.TABLE_TYPE}")


# =============================================================================
# 4) Per a cada UDT candidata, dumpear columnes i 3 files
# =============================================================================
print("\n\n============================================================")
print("4) Columnes + samples de les UDT candidates")
print("============================================================", flush=True)


def dump_table(table_name: str, is_udt: bool = True, n_samples: int = 3):
    real_name = f"@{table_name}" if is_udt else table_name
    escaped = f"[{real_name}]" if is_udt else real_name

    print(f"\n--- COLUMNES {real_name} ---")
    try:
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
            FROM   INFORMATION_SCHEMA.COLUMNS
            WHERE  TABLE_NAME = ?
            ORDER  BY ORDINAL_POSITION
        """, real_name)
        cols = cur.fetchall()
        for c in cols:
            length = c.CHARACTER_MAXIMUM_LENGTH if c.CHARACTER_MAXIMUM_LENGTH is not None else ""
            print(f"    {c.COLUMN_NAME:32} {c.DATA_TYPE:15} {str(length):>6}  {c.IS_NULLABLE}")
    except Exception as e:
        print(f"    [ERROR llegint columnes: {e}]")
        return

    print(f"\n--- SAMPLE {real_name} TOP {n_samples} ---")
    try:
        cur.execute(f"SELECT TOP {n_samples} * FROM {escaped}")
        desc = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if not rows:
            print("    (buit)")
        for i, row in enumerate(rows, 1):
            print(f"    --- fila {i} ---")
            for name, val in zip(desc, row):
                sv = str(val).strip() if val is not None else "NULL"
                if sv and sv != "NULL":
                    print(f"      {name:32} = {sv[:120]}")
    except Exception as e:
        print(f"    [ERROR llegint samples: {e}]")


for udt in udt_candidates:
    dump_table(udt, is_udt=True, n_samples=3)


# =============================================================================
# 5) Comprovar taules SAP nadives sospitoses per delivery/shipping
# =============================================================================
print("\n\n============================================================")
print("5) Taules SAP nadives sospitoses (comprovem existencia)")
print("============================================================", flush=True)

# Candidates SAP standard per gestio de transport/expedicions
NATIVE_CANDIDATES = [
    "ODLN",  # Deliveries
    "DLN1",  # Delivery Lines
    "ORDR",  # Sales Orders
    "RDR1",  # Sales Order Lines
    "OSHP",  # Shipping Types
    "OEDG",  # ??
    "OGCK",  # Gate check
    "AGRD",  # Assignments to trucks (custom SEIDOR?)
]

for t in NATIVE_CANDIDATES:
    try:
        cur.execute("SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?", t)
        exists = cur.fetchone().n > 0
        print(f"  {t:20}  exists={exists}")
    except Exception as e:
        print(f"  {t:20}  ERROR: {e}")


# =============================================================================
# 6) UDF sobre ORDR, ODLN, OITM, OCRD — potser les càrregues son UDF a document natiu
# =============================================================================
print("\n\n============================================================")
print("6) UDF a taules natives sospitoses (ORDR, ODLN, OITM, OCRD, DLN1, RDR1)")
print("============================================================", flush=True)

cur.execute("""
    SELECT TableID, AliasID, Descr, TypeID
    FROM   CUFD
    WHERE  TableID IN ('ORDR','ODLN','OITM','OCRD','DLN1','RDR1')
    ORDER  BY TableID, AliasID
""")
for r in cur.fetchall():
    print(f"  {r.TableID:8} U_{r.AliasID:30}  type={r.TypeID}  descr={(r.Descr or '').strip()}")


conn.close()
print("\n\n[FET]", flush=True)
