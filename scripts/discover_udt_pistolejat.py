"""Discovery efímer: on registra l'addon SEIDOR el pistolejat, i com es
distingeixen els albarans fets pel magatzem. DB_FARINERA_TEST, només lectura.

1) UDT (@...) i UDO amb noms relacionats amb pistolejat/preparació, amb
   columnes i files de mostra.
2) UDF sobre documents de venda (ORDR/RDR1/ODLN/DLN1) amb les mateixes keywords.
3) Albarans (ODLN) dels últims 30 dies agrupats per usuari creador i sèrie,
   per veure quin criteri identifica els "de magatzem".

Ús:
    python scripts/discover_udt_pistolejat.py > pistolejat_report.txt
"""
import os
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
    f"TrustServerCertificate=yes;ApplicationIntent=ReadOnly;APP=DiscoveryPistolejat;"
)

print(f"[INFO] Connectant a {SERVER} / {DATABASE} ...", flush=True)
conn = pyodbc.connect(CS, timeout=15, autocommit=True)
cur = conn.cursor()

# Paraules clau per detectar taules/camps de pistolejat i preparació.
KEYWORDS = (
    "pist", "escan", "scan", "lect", "picking", "pick", "prep", "bult",
    "palet", "pallet", "sscc", "lote", "ubic", "terminal", "pda", "radio",
    "recog", "estat",
)


def _like_clauses(col: str) -> str:
    """Retorna una clàusula OR amb LIKE per cada keyword sobre `col`."""
    parts = [f"UPPER({col}) LIKE '%{kw.upper()}%'" for kw in KEYWORDS]
    return "(" + " OR ".join(parts) + ")"


def _titol(text: str) -> None:
    print("\n\n============================================================")
    print(text)
    print("============================================================", flush=True)


# =============================================================================
# 1) UDT: totes les @SEI* i les candidates per keyword
# =============================================================================
_titol("1) UDT (OUTB): totes les @SEI* + candidates per keyword")

cur.execute("SELECT TableName, Descr, ObjectType FROM OUTB ORDER BY TableName")
udt_rows = cur.fetchall()
print(f"\n[INFO] Total UDT: {len(udt_rows)}")

print("\n--- UDT @SEI* ---")
for r in udt_rows:
    if (r.TableName or "").upper().startswith("SEI"):
        print(f"  @{r.TableName:40}  type={r.ObjectType}  descr={(r.Descr or '').strip()}")

udt_candidates: list[str] = []
for r in udt_rows:
    name = (r.TableName or "").upper()
    descr = (r.Descr or "").upper()
    if any(kw.upper() in name or kw.upper() in descr for kw in KEYWORDS):
        udt_candidates.append(r.TableName)
print(f"\n[INFO] UDT candidates (keyword match): {udt_candidates}")


# =============================================================================
# 2) UDO: objectes d'usuari (el Service Layer els exposa per nom)
# =============================================================================
_titol("2) UDO (OUDO): tots, amb la taula principal")

try:
    cur.execute("SELECT Code, Name, TableName, TYPE FROM OUDO ORDER BY Code")
    for r in cur.fetchall():
        print(f"  {r.Code:30}  table=@{r.TableName:30}  type={r.TYPE}  name={(r.Name or '').strip()}")
except Exception as e:
    print(f"  [ERROR llegint OUDO: {e}]")


# =============================================================================
# 3) UDF a documents de venda amb keyword
# =============================================================================
_titol("3) UDF a ORDR/RDR1/ODLN/DLN1/OITM amb keyword")

cur.execute(f"""
    SELECT TableID, AliasID, Descr, TypeID
    FROM   CUFD
    WHERE  TableID IN ('ORDR','RDR1','ODLN','DLN1','OITM')
      AND  ({_like_clauses("AliasID")} OR {_like_clauses("Descr")})
    ORDER  BY TableID, AliasID
""")
for r in cur.fetchall():
    print(f"  {r.TableID:8} U_{r.AliasID:30}  type={r.TypeID}  descr={(r.Descr or '').strip()}")

print("\n--- Tots els UDF de ODLN (per si l'origen magatzem hi és) ---")
cur.execute("""
    SELECT AliasID, Descr, TypeID FROM CUFD WHERE TableID = 'ODLN' ORDER BY AliasID
""")
for r in cur.fetchall():
    print(f"  U_{r.AliasID:30}  type={r.TypeID}  descr={(r.Descr or '').strip()}")


# =============================================================================
# 4) Columnes + samples de les UDT candidates
# =============================================================================
_titol("4) Columnes + samples de les UDT candidates")


def dump_table(table_name: str, n_samples: int = 3) -> None:
    real_name = f"@{table_name}"
    print(f"\n--- COLUMNES {real_name} ---")
    try:
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM   INFORMATION_SCHEMA.COLUMNS
            WHERE  TABLE_NAME = ?
            ORDER  BY ORDINAL_POSITION
        """, real_name)
        for c in cur.fetchall():
            length = c.CHARACTER_MAXIMUM_LENGTH if c.CHARACTER_MAXIMUM_LENGTH is not None else ""
            print(f"    {c.COLUMN_NAME:32} {c.DATA_TYPE:15} {str(length):>6}")
        cur.execute(f"SELECT COUNT(*) AS n FROM [{real_name}]")
        print(f"    [files: {cur.fetchone().n}]")
    except Exception as e:
        print(f"    [ERROR llegint columnes: {e}]")
        return

    print(f"\n--- SAMPLE {real_name} TOP {n_samples} (les més noves) ---")
    try:
        cur.execute(f"SELECT TOP {n_samples} * FROM [{real_name}] ORDER BY 1 DESC")
        desc = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if not rows:
            print("    (buit)")
        for i, row in enumerate(rows, 1):
            print(f"    --- fila {i} ---")
            for name, val in zip(desc, row):
                sv = str(val).strip() if val is not None else ""
                if sv:
                    print(f"      {name:32} = {sv[:120]}")
    except Exception as e:
        print(f"    [ERROR llegint samples: {e}]")


for udt in udt_candidates:
    dump_table(udt, n_samples=5)


# =============================================================================
# 5) Albarans dels últims 30 dies: per usuari creador i per sèrie
# =============================================================================
_titol("5) ODLN últims 30 dies: per usuari creador i per sèrie")

cur.execute("""
    SELECT U.USER_CODE, U.U_NAME, COUNT(*) AS n,
           SUM(CASE WHEN D.CANCELED <> 'N' THEN 1 ELSE 0 END) AS cancelats
    FROM   ODLN D
    LEFT   JOIN OUSR U ON U.USERID = D.UserSign
    WHERE  D.DocDate >= DATEADD(day, -30, CAST(GETDATE() AS date))
    GROUP  BY U.USER_CODE, U.U_NAME
    ORDER  BY n DESC
""")
print("\n--- Per usuari creador ---")
for r in cur.fetchall():
    print(f"  {str(r.USER_CODE):20} {str(r.U_NAME or ''):30} n={r.n}  cancel·lats={r.cancelats}")

cur.execute("""
    SELECT D.Series, N.SeriesName, COUNT(*) AS n
    FROM   ODLN D
    LEFT   JOIN NNM1 N ON N.Series = D.Series
    WHERE  D.DocDate >= DATEADD(day, -30, CAST(GETDATE() AS date))
    GROUP  BY D.Series, N.SeriesName
    ORDER  BY n DESC
""")
print("\n--- Per sèrie ---")
for r in cur.fetchall():
    print(f"  serie={r.Series:<6} {str(r.SeriesName or ''):20} n={r.n}")

cur.execute("""
    SELECT TOP 5 D.DocEntry, D.DocNum, D.DocDate, D.CardCode, D.DocStatus,
           D.CANCELED, D.Series, D.UserSign, D.Comments
    FROM   ODLN D
    ORDER  BY D.DocEntry DESC
""")
print("\n--- Últims 5 albarans ---")
for r in cur.fetchall():
    print(f"  entry={r.DocEntry} num={r.DocNum} {r.DocDate:%Y-%m-%d} {r.CardCode} "
          f"status={r.DocStatus} canceled={r.CANCELED} serie={r.Series} user={r.UserSign} "
          f"coment={(r.Comments or '')[:60]!r}")


# =============================================================================
# 6) Albarans per usuari: quins camps omple cadascun (origen magatzem?)
# =============================================================================
_titol("6) Últims albarans per usuari creador, amb càrrega i usuari WebApp")

cur.execute("""
    SELECT TOP 40 U.USER_CODE, D.DocEntry, D.DocNum, D.DocDate, D.CardCode,
           D.DocStatus, D.CANCELED, D.U_SEIOrdCargId, D.U_SEIUserWebApp,
           D.U_SEILotExp, D.CreateTS
    FROM   ODLN D
    LEFT   JOIN OUSR U ON U.USERID = D.UserSign
    WHERE  D.DocDate >= DATEADD(day, -60, CAST(GETDATE() AS date))
    ORDER  BY U.USER_CODE, D.DocEntry DESC
""")
for r in cur.fetchall():
    print(f"  {str(r.USER_CODE):10} entry={r.DocEntry} num={r.DocNum} {r.DocDate:%Y-%m-%d} "
          f"{r.CardCode} st={r.DocStatus} canc={r.CANCELED} ordcarg={r.U_SEIOrdCargId} "
          f"webapp={r.U_SEIUserWebApp!r} lot={r.U_SEILotExp!r}")

print("\n--- Albarans amb factura (DLN1.TargetType=13) entre els de 60 dies ---")
cur.execute("""
    SELECT COUNT(DISTINCT D.DocEntry) AS n
    FROM   ODLN D JOIN DLN1 L ON L.DocEntry = D.DocEntry
    WHERE  D.DocDate >= DATEADD(day, -60, CAST(GETDATE() AS date)) AND L.TargetType = 13
""")
print(f"  n={cur.fetchone().n}")


conn.close()
print("\n\n[FET]", flush=True)
