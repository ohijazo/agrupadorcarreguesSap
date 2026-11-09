"""Store d'agrupacions desat a PostgreSQL.

API pública mantinguda igual que la versió JSON anterior perquè els
endpoints Flask no hagin de canviar:

  guardar(nom, carregues, resultat, plantilla=False) -> dict (resum)
  llistar() -> list[dict]
  obtenir(id_) -> dict | None
  eliminar(id_) -> bool
  sincronitza_preparats(id_, fets) -> dict | None   (els fets venen del pistolejat de l'SGA)
  llistar_per_sincronitzar(dies=30) -> list[dict]
  index_carregues_agrupades() -> dict[carrega_id, list[{id, nom, ts, finalitzada}]]
  llistar_plantilles() -> list[dict]

La concurrència es resol a nivell de PostgreSQL (MVCC + transaccions);
ja no cal file lock.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from threading import Lock

import psycopg

import audit
import db

_RE_ID = re.compile(r"^[a-f0-9-]{8,40}$")

# Cache local (per worker) de l'índex carrega_id -> [agrupacions].
# La validesa es comprova contra el comptador global a la taula
# `meta_agrupacions` de PostgreSQL — així workers Gunicorn diferents
# es mantenen coherents sense compartir memòria.
_index_cache: dict[str, list[dict]] | None = None
_index_cache_version: int = -1
_index_lock = Lock()


def _bump_version(cur=None) -> None:
    """Incrementa el comptador global de versió a la BD.

    Si es passa un cursor de psycopg, el bump va dins de la mateixa
    transacció que l'escriptura de dades (atòmic). Si no se'n passa cap,
    obre una connexió pròpia i fa commit immediat (cas de fallback).
    """
    sql = "UPDATE meta_agrupacions SET version = version + 1 WHERE id = 1"
    if cur is not None:
        cur.execute(sql)
    else:
        db.execute(sql)


def get_version() -> int:
    """Versió actual de l'índex d'agrupacions (llegida de la BD).

    Augmenta cada cop que es desa, elimina, marca o desmarca un producte.
    El frontend fa polling d'aquest valor per detectar canvis sense
    re-baixar la llista sencera. Com que es llegeix de la BD, tots els
    workers Gunicorn veuen el mateix valor.
    """
    r = db.fetch_one("SELECT version FROM meta_agrupacions WHERE id = 1")
    return int(r["version"]) if r else 0


def _clear_local_cache() -> None:
    """Reseteja el cache local. Només per a tests — en producció el cache
    s'invalida automàticament quan la versió de BD difereix de la cachejada."""
    global _index_cache, _index_cache_version
    with _index_lock:
        _index_cache = None
        _index_cache_version = -1


def _valida_id(id_: str) -> str:
    if not _RE_ID.fullmatch(id_):
        raise ValueError("id invàlid")
    return id_


# ---------------------------------------------------------------------------
# CRUD bàsic
# ---------------------------------------------------------------------------
def guardar(nom: str, carregues: list[dict], resultat: dict, plantilla: bool = False,
            created_by_id: int | None = None, origen: str = "desada") -> dict:
    if origen not in ("desada", "impresa"):
        raise ValueError(f"origen invàlid: {origen!r}")
    id_ = uuid.uuid4().hex
    nom = (nom or "").strip() or f"Agrupació {datetime.now().isoformat(timespec='seconds')}"
    nom = nom[:80]
    n_carregues = len(carregues or [])
    n_productes = len((resultat or {}).get("productes") or [])
    total_palets_fisics = int((resultat or {}).get("total_palets_fisics") or 0)
    total_sacs = int((resultat or {}).get("total_sacs") or 0)
    plantilla_meta = _calcular_plantilla_meta(carregues) if plantilla else None

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agrupacions
                    (id, nom, plantilla, n_carregues, n_productes,
                     total_palets_fisics, total_sacs,
                     carregues, resultat, plantilla_meta, created_by_id, origen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING ts
                """,
                (
                    id_, nom, plantilla, n_carregues, n_productes,
                    total_palets_fisics, total_sacs,
                    json.dumps(carregues), json.dumps(resultat),
                    json.dumps(plantilla_meta) if plantilla_meta else None,
                    created_by_id, origen,
                ),
            )
            ts_row = cur.fetchone()
            # Index desnormalitzat de càrregues
            if carregues:
                cur.executemany(
                    """
                    INSERT INTO agrupacio_carregues (agrupacio_id, carrega_id, tra_codi)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (id_, c.get("carrega_id"), (c.get("tra_codi") or "").strip() or None)
                        for c in carregues
                        if c.get("carrega_id")
                    ],
                )
            _bump_version(cur)
    audit.log(
        "agrupacio_impresa" if origen == "impresa" else "agrupacio_desada",
        target=id_,
        detall={"nom": nom, "plantilla": plantilla, "n_carregues": n_carregues, "n_productes": n_productes},
    )
    return {
        "id": id_,
        "nom": nom,
        "ts": _format_ts(ts_row["ts"] if ts_row else datetime.now()),
        "n_carregues": n_carregues,
        "n_productes": n_productes,
        "total_palets_fisics": total_palets_fisics,
        "total_sacs": total_sacs,
        "n_preparats": 0,
        "origen": origen,
    }


def llistar() -> list[dict]:
    sql = """
        SELECT a.id, a.nom, a.ts, a.n_carregues, a.n_productes,
               a.total_palets_fisics, a.total_sacs,
               (SELECT COUNT(*) FROM productes_preparats p
                WHERE p.agrupacio_id = a.id) AS n_preparats,
               a.created_by_id, u.nom AS created_by_nom,
               a.finalitzada_manual_at, a.pct_pistolejat
        FROM agrupacions a
        LEFT JOIN usuaris u ON u.id = a.created_by_id
        ORDER BY a.ts DESC
    """
    out = []
    for r in db.fetch_all(sql):
        out.append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "n_carregues": r["n_carregues"],
            "n_productes": r["n_productes"],
            "total_palets_fisics": r["total_palets_fisics"],
            "total_sacs": r["total_sacs"],
            "n_preparats": int(r["n_preparats"] or 0),
            "created_by_id": r["created_by_id"],
            "created_by_nom": r["created_by_nom"],
            "finalitzada_manual_at": _format_ts(r["finalitzada_manual_at"]) if r["finalitzada_manual_at"] else None,
            "pct_pistolejat": r["pct_pistolejat"],
        })
    return out


def llistar_control(origen: str | None = None) -> list[dict]:
    """Llistat per a la pantalla "Gestió d'agrupacions" (/control): agrega
    inici/fi/durada/preparador. Hi surten també les plantilles (`plantilla`),
    perquè la pantalla substitueix la finestra "Agrupacions desades".

    Estats possibles:
      - "pendent": cap producte marcat.
      - "en_curs": algun producte marcat però no tots.
      - "acabada": tots els productes marcats (finalització natural).
      - "tancada": tancada manualment per oficina/admin (preval sobre la resta).

    Quan és "tancada", fi = finalitzada_manual_at i durada compta des de l'inici
    real del checklist (o és NULL si encara no s'havia començat).

    `origen` (opcional): 'desada' o 'impresa' per filtrar; None retorna totes.
    """
    extra_where = ""
    params: list = []
    if origen in ("desada", "impresa"):
        extra_where = " AND a.origen = %s"
        params.append(origen)
    sql = f"""
        SELECT a.id, a.nom, a.ts, a.n_carregues, a.n_productes, a.origen,
               a.plantilla, a.pct_pistolejat, a.total_palets_fisics,
               a.finalitzada_manual_at, ufm.nom AS finalitzada_manual_per_nom,
               COALESCE(agg.n_preparats, 0) AS n_preparats,
               uc.nom AS created_by_nom,
               agg.prep_iniciat, agg.prep_ultim_ts,
               up.nom AS prep_per_nom
        FROM agrupacions a
        LEFT JOIN usuaris uc  ON uc.id  = a.created_by_id
        LEFT JOIN usuaris ufm ON ufm.id = a.finalitzada_manual_per_id
        LEFT JOIN LATERAL (
            SELECT COUNT(*)::INTEGER AS n_preparats,
                   MIN(p.marcat_ts) AS prep_iniciat,
                   MAX(p.marcat_ts) AS prep_ultim_ts,
                   (SELECT marcat_per_id FROM productes_preparats
                    WHERE agrupacio_id = a.id
                    ORDER BY marcat_ts ASC LIMIT 1) AS prep_per_id
            FROM productes_preparats p
            WHERE p.agrupacio_id = a.id
        ) agg ON TRUE
        LEFT JOIN usuaris up ON up.id = agg.prep_per_id
        WHERE TRUE{extra_where}
        ORDER BY a.ts DESC
    """
    out = []
    for r in db.fetch_all(sql, tuple(params) if params else None):
        n_prod = int(r["n_productes"] or 0)
        n_prep = int(r["n_preparats"] or 0)
        prep_iniciat = r["prep_iniciat"]
        fin_manual_at = r["finalitzada_manual_at"]
        completa = n_prod > 0 and n_prep >= n_prod

        if fin_manual_at is not None:
            estat = "tancada"
            prep_finalitzat = fin_manual_at
        elif completa:
            estat = "acabada"
            prep_finalitzat = r["prep_ultim_ts"]
        elif n_prep > 0:
            estat = "en_curs"
            prep_finalitzat = None
        else:
            estat = "pendent"
            prep_finalitzat = None

        durada_s = None
        if prep_iniciat and prep_finalitzat:
            durada_s = int((prep_finalitzat - prep_iniciat).total_seconds())

        out.append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "n_carregues": r["n_carregues"],
            "n_productes": n_prod,
            "n_preparats": n_prep,
            "created_by_nom": r["created_by_nom"],
            "prep_iniciat": _format_ts(prep_iniciat) if prep_iniciat else None,
            "prep_finalitzat": _format_ts(prep_finalitzat) if prep_finalitzat else None,
            "prep_per_nom": r["prep_per_nom"],
            "durada_s": durada_s,
            "estat": estat,
            "origen": r["origen"],
            "plantilla": bool(r["plantilla"]),
            "pct_pistolejat": r["pct_pistolejat"],
            "total_palets_fisics": r["total_palets_fisics"],
            "finalitzada_manual_at": _format_ts(fin_manual_at) if fin_manual_at else None,
            "finalitzada_manual_per_nom": r["finalitzada_manual_per_nom"],
        })
    return out


def obtenir(id_: str) -> dict | None:
    try:
        _valida_id(id_)
    except ValueError:
        return None
    sql = """
        SELECT a.id, a.nom, a.ts, a.plantilla, a.carregues, a.resultat,
               a.plantilla_meta, a.finalitzada_manual_at,
               a.created_by_id, u.nom AS created_by_nom,
               (SELECT array_agg(p.art_codi ORDER BY p.art_codi)
                FROM productes_preparats p
                WHERE p.agrupacio_id = a.id) AS productes_preparats
        FROM agrupacions a
        LEFT JOIN usuaris u ON u.id = a.created_by_id
        WHERE a.id = %s
    """
    r = db.fetch_one(sql, (id_,))
    if not r:
        return None
    detall_rows = db.fetch_all(
        """
        SELECT p.art_codi, p.marcat_ts, p.marcat_per_id, up.nom AS marcat_per_nom
        FROM productes_preparats p
        LEFT JOIN usuaris up ON up.id = p.marcat_per_id
        WHERE p.agrupacio_id = %s
        """,
        (id_,),
    )
    preparats_detall = {
        row["art_codi"]: {
            "ts": _format_ts(row["marcat_ts"]),
            "per_id": row["marcat_per_id"],
            "per_nom": row["marcat_per_nom"],
        }
        for row in detall_rows
    }
    return {
        "id": _id_to_hex(r["id"]),
        "nom": r["nom"],
        "ts": _format_ts(r["ts"]),
        "plantilla": r["plantilla"],
        "carregues": r["carregues"] or [],
        "resultat": r["resultat"] or {},
        "plantilla_meta": r["plantilla_meta"],
        "productes_preparats": list(r["productes_preparats"] or []),
        "preparats_detall": preparats_detall,
        "created_by_id": r["created_by_id"],
        "created_by_nom": r["created_by_nom"],
        "finalitzada_manual_at": _format_ts(r["finalitzada_manual_at"]) if r["finalitzada_manual_at"] else None,
    }


def eliminar(id_: str) -> bool:
    try:
        _valida_id(id_)
    except ValueError:
        return False
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agrupacions WHERE id = %s", (id_,))
            if not cur.rowcount:
                return False
            _bump_version(cur)
    audit.log("agrupacio_eliminada", target=id_)
    return True


# ---------------------------------------------------------------------------
# Productes preparats (magatzem)
# ---------------------------------------------------------------------------
def sincronitza_preparats(id_: str, fets: set[str] | list[str],
                          percent: int | None = None) -> dict | None:
    """Deixa `productes_preparats` igual que `fets`: els productes que el
    pistolejat de l'SGA dona per fets (vegeu `dades.pistolejat.progres_agrupacio`).

    Substitueix el checklist manual: afegeix els que falten (`marcat_ip='SGA'`,
    sense usuari) i treu els que ja no estan fets (p. ex. un albara cancel·lat),
    tambe les marques manuals antigues. Nomes toca la versio i l'auditoria si
    hi ha canvis, perque es crida a cada refresc de la pantalla i des del timer.
    `percent` es el % de kg pistolejats; es desa a `agrupacions.pct_pistolejat`
    perque la pagina principal ensenyi l'avanc parcial.
    Retorna {"afegits", "trets", "percent_canviat"} o None si l'agrupacio no existeix.
    """
    try:
        _valida_id(id_)
    except ValueError:
        return None
    fets = set(fets)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # FOR UPDATE: si l'oficina la tanca a ma mentre consultavem SAP
            # (pot trigar uns segons), aqui ho veiem i no la toquem.
            cur.execute("SELECT pct_pistolejat, finalitzada_manual_at FROM agrupacions "
                        "WHERE id = %s FOR UPDATE", (id_,))
            fila = cur.fetchone()
            if not fila:
                return None
            if isinstance(fila, tuple):
                pct_ara, tancada = fila
            else:
                pct_ara, tancada = fila["pct_pistolejat"], fila["finalitzada_manual_at"]
            if tancada is not None:
                return {"afegits": [], "trets": [], "percent_canviat": False}
            percent_canviat = percent is not None and pct_ara != int(percent)
            if percent_canviat:
                cur.execute("UPDATE agrupacions SET pct_pistolejat = %s WHERE id = %s",
                            (int(percent), id_))
            cur.execute("SELECT art_codi FROM productes_preparats WHERE agrupacio_id = %s", (id_,))
            ara = {r[0] if isinstance(r, tuple) else r["art_codi"] for r in cur.fetchall()}
            afegits = sorted(fets - ara)
            trets = sorted(ara - fets)
            for art in afegits:
                cur.execute(
                    """
                    INSERT INTO productes_preparats (agrupacio_id, art_codi, marcat_ip, marcat_per_id)
                    VALUES (%s, %s, 'SGA', NULL)
                    ON CONFLICT (agrupacio_id, art_codi) DO NOTHING
                    """,
                    (id_, art),
                )
            if trets:
                cur.execute(
                    "DELETE FROM productes_preparats WHERE agrupacio_id = %s AND art_codi = ANY(%s)",
                    (id_, trets),
                )
            if afegits or trets or percent_canviat:
                _bump_version(cur)
    if afegits:
        audit.log("producte_fet_sga", target=id_, detall={"art_codis": afegits})
    if trets:
        audit.log("producte_desfet_sga", target=id_, detall={"art_codis": trets})
    return {"afegits": afegits, "trets": trets, "percent_canviat": percent_canviat}


def llistar_per_sincronitzar(dies: int = 30) -> list[dict]:
    """Agrupacions que el timer del pistolejat ha de mantenir al dia: no
    plantilles, no tancades a ma i creades fa menys de `dies` dies. Hi entren
    tambe les que ja surten acabades: un albara cancel·lat les pot reobrir, i
    les marques manuals d'abans s'han de substituir. Retorna {id, carregues, resultat}."""
    sql = """
        SELECT a.id, a.carregues, a.resultat
        FROM agrupacions a
        WHERE a.plantilla = FALSE
          AND a.finalitzada_manual_at IS NULL
          AND a.ts >= NOW() - make_interval(days => %s)
        ORDER BY a.ts DESC
    """
    return [{"id": _id_to_hex(r["id"]), "carregues": r["carregues"] or [],
             "resultat": r["resultat"] or {}}
            for r in db.fetch_all(sql, (int(dies),))]


def reobrir(id_: str, user_id: int | None = None,
            ip: str | None = None) -> dict | None:
    """Reverteix una finalització manual: torna l'agrupació al seu estat natural."""
    try:
        _valida_id(id_)
    except ValueError:
        return None
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agrupacions
                SET finalitzada_manual_at = NULL,
                    finalitzada_manual_per_id = NULL
                WHERE id = %s
                """,
                (id_,),
            )
            if cur.rowcount == 0:
                return None
            _bump_version(cur)
    audit.log("agrupacio_reoberta", target=id_)
    return obtenir(id_)


def marcar_finalitzada(id_: str, user_id: int | None = None,
                       ip: str | None = None) -> dict | None:
    """Tanca manualment l'agrupació (estat "Tancada") sense tocar productes_preparats.

    Idempotent: si ja estava tancada manualment, no es sobreescriu el qui/quan.
    """
    try:
        _valida_id(id_)
    except ValueError:
        return None
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agrupacions
                SET finalitzada_manual_at = NOW(),
                    finalitzada_manual_per_id = %s
                WHERE id = %s AND finalitzada_manual_at IS NULL
                """,
                (user_id, id_),
            )
            if cur.rowcount == 0:
                cur.execute("SELECT 1 FROM agrupacions WHERE id = %s", (id_,))
                if not cur.fetchone():
                    return None
            _bump_version(cur)
    audit.log("agrupacio_finalitzada_manual", target=id_)
    return obtenir(id_)


# ---------------------------------------------------------------------------
# Índex carrega_id -> agrupacions actives/finalitzades
# ---------------------------------------------------------------------------
def index_carregues_agrupades() -> dict[str, list[dict]]:
    """Per a cada carrega_id, retorna les agrupacions on apareix.

    El cache local es valida contra el comptador de versió global a la BD,
    de manera que tots els workers Gunicorn detecten les escriptures fetes
    pels altres.
    """
    global _index_cache, _index_cache_version

    # Fast-path: si el cache local és vàlid contra la BD, retorna directament
    db_v = get_version()
    with _index_lock:
        if _index_cache is not None and _index_cache_version == db_v:
            return _index_cache

    # Refetch sense lock — no bloquegem altres lectors mentre fem la JOIN
    sql = """
        SELECT ac.carrega_id, v.id, v.nom, v.ts, v.finalitzada,
               v.n_productes, v.n_preparats, a.pct_pistolejat
        FROM agrupacio_carregues ac
        JOIN v_agrupacions_estat v ON v.id = ac.agrupacio_id
        JOIN agrupacions a ON a.id = ac.agrupacio_id
        ORDER BY v.ts DESC
    """
    index: dict[str, list[dict]] = {}
    for r in db.fetch_all(sql):
        index.setdefault(r["carrega_id"], []).append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "finalitzada": bool(r["finalitzada"]),
            "n_productes": int(r["n_productes"] or 0),
            "n_preparats": int(r["n_preparats"] or 0),
            "pct_pistolejat": r["pct_pistolejat"],
        })

    # Re-llegim la versió després del fetch: si entremig algú ha escrit,
    # la propera trucada veurà cached_v != db_v i tornarà a refrescar.
    new_db_v = get_version()
    with _index_lock:
        _index_cache = index
        _index_cache_version = new_db_v
    return index


# ---------------------------------------------------------------------------
# Plantilles
# ---------------------------------------------------------------------------
def _calcular_plantilla_meta(carregues: list[dict]) -> dict:
    """Extreu els atributs comuns d'una plantilla a partir de les seves càrregues."""
    transportistes: dict[str, str] = {}
    for c in carregues or []:
        tc = (c.get("tra_codi") or "").strip()
        if tc:
            transportistes.setdefault(tc, (c.get("transportista") or "").strip())
    return {
        "transportistes": [
            {"tra_codi": tc, "tra_nom": nm} for tc, nm in sorted(transportistes.items())
        ],
        "n_carregues_tipic": len(carregues or []),
    }


def llistar_plantilles() -> list[dict]:
    sql = """
        SELECT id, nom, ts, plantilla_meta, n_carregues
        FROM agrupacions
        WHERE plantilla = TRUE
        ORDER BY ts DESC
    """
    out = []
    for r in db.fetch_all(sql):
        meta = r["plantilla_meta"] or {}
        out.append({
            "id": _id_to_hex(r["id"]),
            "nom": r["nom"],
            "ts": _format_ts(r["ts"]),
            "transportistes": meta.get("transportistes", []),
            "n_carregues_tipic": meta.get("n_carregues_tipic", r["n_carregues"]),
        })
    return out


# ---------------------------------------------------------------------------
# Helpers de format (per mantenir compatibilitat amb la API existent)
# ---------------------------------------------------------------------------
def _id_to_hex(value) -> str:
    """psycopg torna UUID; el codi existing espera hex string."""
    if value is None:
        return ""
    if isinstance(value, uuid.UUID):
        return value.hex
    return str(value).replace("-", "")


def _format_ts(value) -> str:
    """Tornar timestamp en isoformat segons (sense microsegons) per compatibilitat."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


# Manté `_es_finalitzada` per compatibilitat amb tests antics que el cridessin
def _es_finalitzada(obj: dict) -> bool:
    n_prods = len((obj.get("resultat") or {}).get("productes") or [])
    n_prep = len(obj.get("productes_preparats") or [])
    return n_prods > 0 and n_prep >= n_prods
