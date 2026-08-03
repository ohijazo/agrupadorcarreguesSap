"""Efimer: consulta la distribucio real de U_SEIEstado a @SEI_ORDENCARGA."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import consultes_carregues as c

conn = c.connectar()
try:
    print('=== Tots els valors U_SEIEstado a @SEI_ORDENCARGA ===')
    rows = conn.execute("""
        SELECT U_SEIEstado, COUNT(*) AS n,
               MIN(U_SEIDataS) AS min_dataS,
               MAX(U_SEIDataS) AS max_dataS,
               SUM(CASE WHEN Canceled = 'Y' THEN 1 ELSE 0 END) AS n_canceled
        FROM   [@SEI_ORDENCARGA]
        GROUP BY U_SEIEstado
        ORDER BY U_SEIEstado
    """).fetchall()
    for r in rows:
        print(f'  U_SEIEstado={r.U_SEIEstado!r:8}  n={r.n:4}  n_canceled={r.n_canceled}  dataS rang: {r.min_dataS} -> {r.max_dataS}')

    print()
    print('=== Mostra de 3 carregues per cada estat (excloent Canceled) ===')
    for r in rows:
        estat = r.U_SEIEstado
        if estat is None:
            cond = "IS NULL"
            params = ()
        else:
            cond = "= ?"
            params = (estat,)
        sql = f"""
            SELECT TOP 3 DocEntry, DocNum, CAST(U_SEINomCarg AS varchar(80)) AS nom,
                   U_SEIDataS, U_SEIDataT, RTRIM(U_SEITransp) AS trans, U_SEIEstado
            FROM   [@SEI_ORDENCARGA]
            WHERE  U_SEIEstado {cond}
              AND  (Canceled IS NULL OR Canceled <> 'Y')
            ORDER BY DocEntry DESC
        """
        subq = conn.execute(sql, *params).fetchall()
        print(f'  --- estat={estat!r} ---')
        for s in subq:
            nom = (s.nom or '')[:40]
            print(f'    DE={s.DocEntry:4} DN={s.DocNum:4} nom={nom!r} dataS={s.U_SEIDataS} dataT={s.U_SEIDataT} trans={s.trans}')
finally:
    conn.close()
