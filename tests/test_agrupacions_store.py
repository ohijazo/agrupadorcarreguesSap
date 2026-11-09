"""Tests d'agrupacions_store: persistència JSON, índex de càrregues agrupades i reset."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agrupacions_store  # noqa: E402

# La fixture `store_tmp` ara viu a conftest.py i fa TRUNCATE de les taules
# de PostgreSQL en lloc d'usar un directori temporal. Els tests que cridin
# `store_tmp` faran skip automàticament si no hi ha PG_HOST configurat.


def _resultat(productes=("ART1",)):
    return {
        "productes": [{"art_codi": p, "art_descrip": p} for p in productes],
        "total_palets_fisics": 1,
        "total_sacs": 10,
    }


def _carrega(cid="2026/01/0000001"):
    return {
        "eje_ejercicio": "2026", "sca_serie": "01", "car_numero": "0000001",
        "carrega_id": cid,
    }


# --- guardar / obtenir / eliminar ----------------------------------------

def test_guardar_i_obtenir(store_tmp):
    info = agrupacions_store.guardar("Test", [_carrega()], _resultat())
    assert info["id"] and info["nom"] == "Test"
    obj = agrupacions_store.obtenir(info["id"])
    assert obj is not None
    assert obj["nom"] == "Test"
    assert obj["productes_preparats"] == []


def test_eliminar(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega()], _resultat())
    assert agrupacions_store.eliminar(info["id"]) is True
    assert agrupacions_store.obtenir(info["id"]) is None


# --- index_carregues_agrupades --------------------------------------------

def test_index_buit_quan_no_hi_ha_agrupacions(store_tmp):
    assert agrupacions_store.index_carregues_agrupades() == {}


def test_index_indica_carrega_en_agrupacio_activa(store_tmp):
    info = agrupacions_store.guardar("Activa", [_carrega("2026/01/0000123")], _resultat(("A", "B")))
    idx = agrupacions_store.index_carregues_agrupades()
    entries = idx.get("2026/01/0000123") or []
    assert len(entries) == 1
    assert entries[0]["id"] == info["id"]
    assert entries[0]["finalitzada"] is False


def test_index_marca_finalitzada_quan_tots_preparats(store_tmp):
    info = agrupacions_store.guardar("Acabada", [_carrega("2026/01/0000999")], _resultat(("A", "B")))
    agrupacions_store.sincronitza_preparats(info["id"], {"A", "B"})
    idx = agrupacions_store.index_carregues_agrupades()
    entries = idx["2026/01/0000999"]
    assert entries[0]["finalitzada"] is True


def test_index_diferencia_activa_de_finalitzada(store_tmp):
    a = agrupacions_store.guardar("Activa", [_carrega("2026/01/0000001")], _resultat(("X",)))
    b = agrupacions_store.guardar("Acabada", [_carrega("2026/01/0000002")], _resultat(("Y",)))
    agrupacions_store.sincronitza_preparats(b["id"], {"Y"})
    idx = agrupacions_store.index_carregues_agrupades()
    assert idx["2026/01/0000001"][0]["finalitzada"] is False
    assert idx["2026/01/0000002"][0]["finalitzada"] is True


def test_index_carrega_present_en_dues_agrupacions(store_tmp):
    cid = "2026/01/0000555"
    agrupacions_store.guardar("A1", [_carrega(cid)], _resultat(("X",)))
    agrupacions_store.guardar("A2", [_carrega(cid)], _resultat(("Y",)))
    idx = agrupacions_store.index_carregues_agrupades()
    assert len(idx[cid]) == 2


def test_index_es_recalcula_despres_eliminar(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega("2026/01/0000007")], _resultat())
    assert "2026/01/0000007" in agrupacions_store.index_carregues_agrupades()
    agrupacions_store.eliminar(info["id"])
    assert "2026/01/0000007" not in agrupacions_store.index_carregues_agrupades()


# --- sincronitza_preparats (pistolejat de l'SGA) ---------------------------

def test_sincronitza_afegeix_i_treu(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega()], _resultat(("A", "B", "C")))
    r = agrupacions_store.sincronitza_preparats(info["id"], {"A", "B"})
    assert r == {"afegits": ["A", "B"], "trets": []}
    obj = agrupacions_store.obtenir(info["id"])
    assert obj["productes_preparats"] == ["A", "B"]
    # Sense usuari: ho ha fet l'SGA.
    assert obj["preparats_detall"]["A"]["per_id"] is None

    # Albara cancel·lat: B torna a estar pendent.
    r = agrupacions_store.sincronitza_preparats(info["id"], {"A", "C"})
    assert r == {"afegits": ["C"], "trets": ["B"]}
    assert agrupacions_store.obtenir(info["id"])["productes_preparats"] == ["A", "C"]


def test_sincronitza_sense_canvis_no_toca_la_versio(store_tmp):
    info = agrupacions_store.guardar("X", [_carrega()], _resultat(("A",)))
    agrupacions_store.sincronitza_preparats(info["id"], {"A"})
    v = agrupacions_store.get_version()
    assert agrupacions_store.sincronitza_preparats(info["id"], {"A"}) == {"afegits": [], "trets": []}
    assert agrupacions_store.get_version() == v


def test_sincronitza_id_inexistent_o_invalid(store_tmp):
    assert agrupacions_store.sincronitza_preparats("a" * 32, {"A"}) is None
    assert agrupacions_store.sincronitza_preparats("../etc/passwd", {"A"}) is None


def test_sincronitza_concurrent_queda_consistent(store_tmp):
    """Pantalla i timer sincronitzen alhora: no peta i queda un dels dos estats."""
    import threading
    info = agrupacions_store.guardar("Y", [_carrega()], _resultat(("A", "B")))
    id_ = info["id"]
    barrier = threading.Barrier(2)

    def sincro(fets):
        barrier.wait()
        agrupacions_store.sincronitza_preparats(id_, fets)

    t1 = threading.Thread(target=sincro, args=({"A"},))
    t2 = threading.Thread(target=sincro, args=({"A", "B"},))
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert set(agrupacions_store.obtenir(id_)["productes_preparats"]) in ({"A"}, {"A", "B"})


def test_llistar_per_sincronitzar_salta_tancades_i_plantilles(store_tmp):
    viva = agrupacions_store.guardar("Viva", [_carrega("2026/01/0000001")], _resultat(("A",)))
    tancada = agrupacions_store.guardar("Tancada", [_carrega("2026/01/0000002")], _resultat(("A",)))
    agrupacions_store.marcar_finalitzada(tancada["id"])
    ids = {o["id"] for o in agrupacions_store.llistar_per_sincronitzar(30)}
    assert viva["id"] in ids and tancada["id"] not in ids


# --- Plantilles ---------------------------------------------------------

def _carrega_amb_tra(cid, tra_codi, tra_nom):
    c = _carrega(cid)
    c["tra_codi"] = tra_codi
    c["transportista"] = tra_nom
    return c


def test_guardar_plantilla_calcula_meta(store_tmp):
    info = agrupacions_store.guardar(
        "Mascó dilluns",
        [
            _carrega_amb_tra("2026/01/0000001", "T01", "Mascó SA"),
            _carrega_amb_tra("2026/01/0000002", "T01", "Mascó SA"),
            _carrega_amb_tra("2026/01/0000003", "T02", "Altre"),
        ],
        _resultat(),
        plantilla=True,
    )
    obj = agrupacions_store.obtenir(info["id"])
    assert obj["plantilla"] is True
    meta = obj["plantilla_meta"]
    assert meta["n_carregues_tipic"] == 3
    codis = {t["tra_codi"] for t in meta["transportistes"]}
    assert codis == {"T01", "T02"}


def test_guardar_sense_plantilla_no_te_meta(store_tmp):
    info = agrupacions_store.guardar("Normal", [_carrega()], _resultat(), plantilla=False)
    obj = agrupacions_store.obtenir(info["id"])
    assert obj.get("plantilla") is False
    # `plantilla_meta` és None per a agrupacions normals (no plantilles)
    assert obj.get("plantilla_meta") is None


def test_llistar_plantilles_nomes_les_marcades(store_tmp):
    agrupacions_store.guardar("A", [_carrega_amb_tra("2026/01/0001", "T01", "X")], _resultat(), plantilla=True)
    agrupacions_store.guardar("B", [_carrega()], _resultat(), plantilla=False)
    agrupacions_store.guardar("C", [_carrega_amb_tra("2026/01/0002", "T03", "Z")], _resultat(), plantilla=True)
    plantilles = agrupacions_store.llistar_plantilles()
    assert len(plantilles) == 2
    noms = {p["nom"] for p in plantilles}
    assert noms == {"A", "C"}


def test_llistar_plantilles_amb_transportistes(store_tmp):
    agrupacions_store.guardar(
        "X",
        [_carrega_amb_tra("2026/01/0001", "T01", "Trans U")],
        _resultat(),
        plantilla=True,
    )
    plantilles = agrupacions_store.llistar_plantilles()
    assert plantilles[0]["transportistes"][0]["tra_codi"] == "T01"
    assert plantilles[0]["transportistes"][0]["tra_nom"] == "Trans U"


# --- Comptador de versió compartit (sincronitza workers Gunicorn) ---------

def test_version_creix_amb_cada_escriptura(store_tmp):
    """Cada operació d'escriptura ha de bumpar el comptador a la BD."""
    v0 = agrupacions_store.get_version()
    info = agrupacions_store.guardar("V", [_carrega()], _resultat(("A", "B")))
    v1 = agrupacions_store.get_version()
    assert v1 > v0

    agrupacions_store.sincronitza_preparats(info["id"], {"A"})
    v2 = agrupacions_store.get_version()
    assert v2 > v1

    agrupacions_store.sincronitza_preparats(info["id"], set())
    v3 = agrupacions_store.get_version()
    assert v3 > v2

    agrupacions_store.marcar_finalitzada(info["id"])
    v4 = agrupacions_store.get_version()
    assert v4 > v3

    agrupacions_store.eliminar(info["id"])
    v5 = agrupacions_store.get_version()
    assert v5 > v4


def test_cache_revalida_si_canvia_versio_BD_des_de_fora(store_tmp):
    """Simula un altre worker Gunicorn: una escriptura externa al store
    bumpa la versió a la BD; la propera lectura ha de refer el cache."""
    import db

    cid = "2026/01/0000321"
    info = agrupacions_store.guardar("Inicial", [_carrega(cid)], _resultat(("X",)))
    idx1 = agrupacions_store.index_carregues_agrupades()
    assert info["id"] in {e["id"] for e in idx1.get(cid, [])}

    # Cache local validada amb la versió actual. Simulem el cas "el cache del
    # nostre worker es queda obsolet perquè un altre worker ha eliminat una
    # agrupació": esborrem la fila i bumpem el comptador per fora del store.
    db.execute("DELETE FROM agrupacions WHERE id = %s", (info["id"],))
    db.execute("UPDATE meta_agrupacions SET version = version + 1 WHERE id = 1")

    idx2 = agrupacions_store.index_carregues_agrupades()
    assert info["id"] not in {e["id"] for e in idx2.get(cid, [])}


def test_cache_hit_si_versio_no_canvia(store_tmp, monkeypatch):
    """Dues lectures consecutives sense escriptures només han de fer la JOIN
    una vegada — la segona ha de servir del cache local."""
    import db
    agrupacions_store.guardar("Cached", [_carrega("2026/01/0000777")], _resultat(("Z",)))

    # Omple el cache amb la primera lectura
    agrupacions_store.index_carregues_agrupades()

    # Comptem quantes vegades es crida db.fetch_all amb la query de l'índex
    calls = {"n": 0}
    orig_fetch_all = db.fetch_all

    def counting_fetch_all(sql, params=None):
        if "agrupacio_carregues" in sql and "v_agrupacions_estat" in sql:
            calls["n"] += 1
        return orig_fetch_all(sql, params)

    monkeypatch.setattr(db, "fetch_all", counting_fetch_all)

    agrupacions_store.index_carregues_agrupades()
    agrupacions_store.index_carregues_agrupades()
    assert calls["n"] == 0, "El cache local hauria d'haver respost sense fer la JOIN"
