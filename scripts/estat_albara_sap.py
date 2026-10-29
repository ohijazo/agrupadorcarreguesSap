"""Fotografia de l'estat d'un albara a SAP i del que en depen. Nomes lectura.

Serveix per veure a TEST que fa SAP (i l'addon SEIDOR / SGA) quan es
cancel·la un albara des de l'app: executeu-lo abans i despres de cancel·lar i
compareu les dues sortides.

    python scripts/estat_albara_sap.py 148 > abans.txt
    (cancel·lar l'albara 148 des de l'app)
    python scripts/estat_albara_sap.py 148 > despres.txt

Mostra:
  - l'albara (ODLN): estat, cancel·lat, usuari, carrega;
  - el document de cancel·lacio, si n'hi ha (ODLN amb CANCELED = 'C' basat en l'albara);
  - les linies de les comandes d'origen (RDR1): estat i quantitat oberta;
  - les files de `@SEIOPIC` d'aquestes comandes (el pistolejat);
  - els ultims estats de `@SEIESTATSCOM` de cada comanda.
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

if len(sys.argv) != 2 or not sys.argv[1].isdigit():
    sys.exit("Us: python scripts/estat_albara_sap.py DOCENTRY")
DOC = int(sys.argv[1])

CS = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={os.environ['SAP_SQL_SERVER']};DATABASE={os.environ['SAP_SQL_DATABASE']};"
    f"UID={os.environ['SAP_SQL_USER']};PWD={os.environ['SAP_SQL_PASSWORD']};"
    f"TrustServerCertificate=yes;ApplicationIntent=ReadOnly;APP=EstatAlbaraSAP;"
)
cur = pyodbc.connect(CS, timeout=15, autocommit=True).cursor()


def taula(titol, sql, *params):
    files = cur.execute(sql, *params).fetchall()
    print(f"\n== {titol} ({len(files)})")
    if files:
        cols = [d[0] for d in cur.description]
        print(" | ".join(cols))
        for f in files:
            print(" | ".join("" if v is None else str(v).strip() for v in f))
    return files


print(f"Base de dades: {os.environ['SAP_SQL_DATABASE']} - albara DocEntry {DOC}")

if not taula("Albara", """
        SELECT o.DocEntry, o.DocNum, o.DocDate, o.DocStatus, o.CANCELED, o.UserSign,
               u.USER_CODE, o.U_SEIOrdCargId AS carrega, o.UpdateDate, o.UpdateTS
        FROM ODLN o LEFT JOIN OUSR u ON u.USERID = o.UserSign
        WHERE o.DocEntry = ?""", DOC):
    sys.exit("No existeix")

taula("Document de cancelacio", """
        SELECT DISTINCT o.DocEntry, o.DocNum, o.DocDate, o.CANCELED, o.UserSign, o.CreateTS
        FROM ODLN o JOIN DLN1 l ON l.DocEntry = o.DocEntry
        WHERE o.CANCELED = 'C' AND l.BaseType = 15 AND l.BaseEntry = ?""", DOC)

comandes = sorted({r.BaseEntry for r in cur.execute(
    "SELECT DISTINCT BaseEntry FROM DLN1 WHERE DocEntry = ? AND BaseType = 17", DOC).fetchall()})
if not comandes:
    sys.exit("\nL'albara no ve de cap comanda de venda.")
ph = ",".join("?" * len(comandes))

taula("Linies de l'albara", """
        SELECT LineNum, ItemCode, Quantity, InvQty, LineStatus, BaseEntry, BaseLine, TargetType, TrgetEntry
        FROM DLN1 WHERE DocEntry = ? ORDER BY LineNum""", DOC)

taula("Linies de les comandes d'origen", f"""
        SELECT r.DocEntry AS comanda, o.DocNum, r.LineNum, r.ItemCode, r.Quantity, r.OpenQty,
               r.OpenInvQty, r.LineStatus, r.TargetType, r.TrgetEntry
        FROM RDR1 r JOIN ORDR o ON o.DocEntry = r.DocEntry
        WHERE r.DocEntry IN ({ph}) ORDER BY r.DocEntry, r.LineNum""", *comandes)

taula("@SEIOPIC (pistolejat) de les comandes", f"""
        SELECT Code, U_DocEntry AS carrega, U_BaseEntry AS comanda, U_BaseLine AS linia,
               U_ItemCode, U_MdAbsEntry AS lot, U_Quantity, U_InvQty, U_TargetType, U_TargetEntry
        FROM [@SEIOPIC] WHERE U_BaseObject = 17 AND U_BaseEntry IN ({ph})
        ORDER BY U_BaseEntry, U_BaseLine, Code""", *comandes)

taula("@SEIESTATSCOM (ultims 5 estats per comanda)", f"""
        SELECT U_SEIDocEntry AS comanda, Code, U_SEIEstado, U_SEIFecha, U_SEIHora
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY U_SEIDocEntry ORDER BY CAST(Code AS int) DESC) AS n
              FROM [@SEIESTATSCOM] WHERE U_SEIDocEntry IN ({ph})) e
        WHERE n <= 5 ORDER BY U_SEIDocEntry, CAST(Code AS int) DESC""", *comandes)
