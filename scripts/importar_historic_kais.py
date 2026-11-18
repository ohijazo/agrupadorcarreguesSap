"""Importa l'historic de KAIS (fitxer de `exportar_historic.py` de l'app de KAIS).

Perque el 23/11/2026 l'usuari no noti que l'app ara llegeix de SAP:
  - usuaris: es creen els que no hi son (per `username`), amb el mateix hash
    de contrasenya, rol i estat. Els que ja hi son no es toquen.
  - agrupacions: es copien amb els productes preparats i les carregues,
    conservant l'id (UUID). Les que ja hi son no es toquen. Els usuaris que
    hi surten (qui l'ha creada, qui ha marcat...) es tradueixen a l'id d'aqui.
  - carregues del calendari: a `historic_carregues`, substituint les que hi
    hagues d'una importacio anterior.

Es pot tornar a executar: no duplica res.

Us:
    python scripts/importar_historic_kais.py /var/tmp/historic_kais.json
    python scripts/importar_historic_kais.py fitxer.json --simular   # no escriu res
"""
import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import app  # noqa: F401,E402  (carrega el .env i el pool de PostgreSQL)
import db  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

_MIGRACIO = os.path.join(_ROOT, "db", "migrations", "009_historic_kais.sql")
_FK_USUARI = {
    "agrupacions": ("created_by_id", "finalitzada_manual_per_id"),
    "productes_preparats": ("marcat_per_id",),
}


def _columnes(cur, taula: str) -> dict[str, str]:
    cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s", (taula,))
    return {r["column_name"]: r["data_type"] for r in cur.fetchall()}


def _insereix(cur, taula: str, files: list[dict], conflicte: str) -> int:
    """INSERT ... ON CONFLICT DO NOTHING amb les columnes que existeixen aqui."""
    cols = _columnes(cur, taula)
    n = 0
    for f in files:
        noms = [k for k in f if k in cols]
        vals = [Jsonb(f[k]) if cols[k] == "jsonb" and f[k] is not None else f[k] for k in noms]
        cur.execute(
            f"INSERT INTO {taula} ({', '.join(noms)}) VALUES ({', '.join(['%s'] * len(noms))}) "
            f"ON CONFLICT ({conflicte}) DO NOTHING", vals)
        n += cur.rowcount
    return n


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("fitxer")
    p.add_argument("--simular", action="store_true", help="Ho fa tot i al final desfa.")
    args = p.parse_args()
    with open(args.fitxer, encoding="utf-8") as f:
        d = json.load(f)
    print(f"Fitxer generat {d['generat']} - carregues {d['desde']} .. {d['fins']}")

    with db.get_conn() as conn, conn.cursor() as cur:
        with open(_MIGRACIO, encoding="utf-8") as m:
            cur.execute(m.read())

        # --- usuaris: per username; mapa id KAIS -> id d'aqui
        cur.execute("SELECT id, username FROM usuaris")
        aqui = {r["username"]: r["id"] for r in cur.fetchall()}
        nous = 0
        mapa: dict[int, int] = {}
        for u in d["usuaris"]:
            if u["username"] not in aqui:
                cur.execute(
                    "INSERT INTO usuaris (username, password_hash, nom, rol, actiu, created_at, last_login_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (u["username"], u["password_hash"], u["nom"], u["rol"], u["actiu"],
                     u["created_at"], u["last_login_at"]))
                aqui[u["username"]] = cur.fetchone()["id"]
                nous += 1
            mapa[u["id"]] = aqui[u["username"]]
        print(f"  usuaris: {nous} nous, {len(d['usuaris']) - nous} ja hi eren")

        # --- agrupacions i dependents, amb els usuaris traduits
        for taula, camps in _FK_USUARI.items():
            for f in d[taula]:
                for c in camps:
                    if f.get(c) is not None:
                        f[c] = mapa.get(f[c])
        n_agr = _insereix(cur, "agrupacions", d["agrupacions"], "id")
        n_pp = _insereix(cur, "productes_preparats", d["productes_preparats"], "agrupacio_id, art_codi")
        n_ac = _insereix(cur, "agrupacio_carregues", d["agrupacio_carregues"], "agrupacio_id, carrega_id")
        print(f"  agrupacions: {n_agr} noves de {len(d['agrupacions'])} "
              f"({n_pp} productes preparats, {n_ac} carregues)")
        if n_agr:
            # Invalida el cache de l'index carrega -> agrupacions de tots els workers.
            cur.execute("UPDATE meta_agrupacions SET version = version + 1 WHERE id = 1")

        # --- carregues del calendari
        sense_detall = 0
        for c in d["carregues"]:
            it = c["item"]
            it.pop("agrupacions", None)   # es recalcula a cada consulta amb les d'aqui
            data_cal = (it.get("car_fecsalida") or it.get("car_fecha") or "")[:10]
            if not data_cal:
                continue
            sense_detall += c["detall"] is None
            cur.execute(
                """INSERT INTO historic_carregues (carrega_id, data_cal, item, detall)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (carrega_id) DO UPDATE
                      SET data_cal = EXCLUDED.data_cal, item = EXCLUDED.item,
                          detall = EXCLUDED.detall, importat_at = NOW()""",
                (it["carrega_id"], data_cal, Jsonb(it),
                 Jsonb(c["detall"]) if c["detall"] is not None else None))
        print(f"  carregues: {len(d['carregues'])} ({sense_detall} sense detall)")

        if args.simular:
            conn.rollback()
            print("SIMULACIO: no s'ha desat res.")
            return 0
    print("OK - historic de KAIS importat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
