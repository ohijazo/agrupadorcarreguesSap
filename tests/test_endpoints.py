"""Tests dels endpoints Flask amb monkeypatch del store i del motor.

Els endpoints que toquen SQL Server (llistar_carregues, etc.) no es proven
aquí — caldria una BD real o mocks més complexos. Aquí cobrim la lògica
HTTP (validació, 404/409, audit log) i la integració amb el store.
"""
import os
import sys
import types
import json

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# Stub motor/models abans d'importar app (per evitar import errors si la
# dependència germana no està disponible)
sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


@pytest.fixture
def client(store_tmp):
    """test_client de Flask amb la BD ja netejada per la fixture compartida.
    Desactivem CSRF perquè aquests tests no l'envien — el comportament CSRF
    queda cobert per test_csrf.py específicament."""
    import app as app_module
    app_module.app.config["TESTING"] = True
    app_module.app.config["CSRF_ENABLED"] = False
    with app_module.app.test_client() as c:
        yield c
    app_module.app.config.pop("CSRF_ENABLED", None)


def _carrega(cid="2026/01/0000001"):
    return {
        "carrega_id": cid,
        "eje_ejercicio": "2026",
        "sca_serie": "01",
        "car_numero": cid.split("/")[-1],
    }


def _resultat(productes=("A",)):
    return {
        "productes": [{"art_codi": p, "art_descrip": p} for p in productes],
        "total_palets_fisics": 1,
        "total_sacs": 5,
    }


# --- /api/agrupacions ----------------------------------------------------
def test_guardar_agrupacio(client):
    r = client.post("/api/agrupacions", json={
        "nom": "Test 1", "carregues": [_carrega()], "resultat": _resultat(),
    })
    assert r.status_code == 200
    d = r.get_json()
    assert d["nom"] == "Test 1"
    assert d["n_carregues"] == 1
    assert "id" in d


def test_guardar_sense_nom_es_400(client):
    r = client.post("/api/agrupacions", json={
        "nom": "", "carregues": [_carrega()], "resultat": _resultat(),
    })
    assert r.status_code == 400


def test_guardar_sense_carregues_es_400(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [], "resultat": _resultat(),
    })
    assert r.status_code == 400


def test_obtenir_agrupacio_no_trobada(client):
    r = client.get("/api/agrupacions/" + "a" * 32)
    assert r.status_code == 404


def test_eliminar_agrupacio(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(),
    })
    id_ = r.get_json()["id"]
    r = client.delete(f"/api/agrupacions/{id_}")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    r = client.get(f"/api/agrupacions/{id_}")
    assert r.status_code == 404


def test_eliminar_inexistent(client):
    r = client.delete("/api/agrupacions/" + "b" * 32)
    assert r.status_code == 404


# --- /api/agrupacions/<id>/pistolejat (substitueix el checklist manual) --
def _dades_sga(linies):
    """`linies`: [(art_codi, kg_oberts)] d'una comanda de la carrega 1."""
    return {
        "comandes": [{"docentry": 500, "docnum": 1, "carrega": 1, "cli_codi": "C", "cli_nom": "",
                      "linies": [{"linia": i, "art_codi": art, "art_descrip": art, "unitat": "S25",
                                  "sacs": 40, "kg": 1000, "kg_oberts": oberts}
                                 for i, (art, oberts) in enumerate(linies)]}],
        "pistolejats": [],
        "estats": {},
    }


def _agrupacio_amb_carrega(client, productes=("A", "B")):
    resultat = {
        "productes": [{"art_codi": a, "art_descrip": a,
                       "per_carrega": [{"carrega_id": "2026/01/0000001"}]} for a in productes],
        "total_palets_fisics": 1, "total_sacs": 5,
    }
    return client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": resultat}).get_json()["id"]


def test_pistolejat_informa_pero_no_toca_la_produccio(client, monkeypatch):
    """Agrupar és per produir i pistolejar per expedir: el pistolejat no marca
    cap producte com a produït, només en desa el %."""
    import preparacio_sga
    id_ = _agrupacio_amb_carrega(client)
    client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "B", "preparat": True})
    rebut = []
    monkeypatch.setattr(preparacio_sga, "obtenir_dades_pistolejat",
                        lambda ids, incloure_tancades=False: rebut.append((ids, incloure_tancades))
                        or _dades_sga([("A", 0), ("B", 1000)]))
    monkeypatch.setattr(preparacio_sga, "_cache", {})
    j = client.get(f"/api/agrupacions/{id_}/pistolejat").get_json()
    assert j["productes"]["A"]["estat"] == "complet" and j["productes"]["B"]["estat"] == "pendent"
    assert rebut == [([1], True)]
    obj = client.get(f"/api/agrupacions/{id_}").get_json()
    assert obj["productes_preparats"] == ["B"]          # la marca de producció, intacta


def test_pistolejat_inexistent(client):
    assert client.get("/api/agrupacions/" + "c" * 32 + "/pistolejat").status_code == 404


def test_marcar_producte(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(("A", "B")),
    })
    id_ = r.get_json()["id"]
    r = client.patch(f"/api/agrupacions/{id_}/producte",
                     json={"art_codi": "A", "preparat": True})
    assert r.status_code == 200
    assert r.get_json()["n_preparats"] == 1


def test_desmarcar_producte(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(("A",)),
    })
    id_ = r.get_json()["id"]
    client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "A", "preparat": True})
    r = client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "A", "preparat": False})
    assert r.status_code == 200
    assert r.get_json()["n_preparats"] == 0


def test_reset_preparats(client):
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega()], "resultat": _resultat(("A", "B", "C")),
    })
    id_ = r.get_json()["id"]
    for art in ("A", "B"):
        client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": art, "preparat": True})
    r = client.post(f"/api/agrupacions/{id_}/reset-preparats")
    assert r.status_code == 200
    assert r.get_json()["n_preparats"] == 0


def test_reset_preparats_inexistent(client):
    r = client.post("/api/agrupacions/" + "c" * 32 + "/reset-preparats")
    assert r.status_code == 404


# --- /api/agrupar (validació 409 duplicats) -----------------------------
def test_agrupar_409_si_ja_agrupada(client, monkeypatch):
    # Guardem agrupació amb càrrega X
    r = client.post("/api/agrupacions", json={
        "nom": "Activa", "carregues": [_carrega("2026/01/0000777")], "resultat": _resultat(),
    })
    assert r.status_code == 200
    agrup_id = r.get_json()["id"]
    # Provem d'agrupar la mateixa càrrega → 409
    r = client.post("/api/agrupar", json={"carregues": [_carrega("2026/01/0000777")]})
    assert r.status_code == 409
    d = r.get_json()
    assert "duplicats" in d
    dup = d["duplicats"][0]
    assert dup["carrega_id"] == "2026/01/0000777"
    # La resposta ha d'incloure l'agrupació afectada amb id+nom per al
    # deep-link del modal de duplicats (botons "Veure" i "Eliminar").
    assert dup.get("agrupacions"), "Falta llistat d'agrupacions afectades"
    ag = dup["agrupacions"][0]
    assert ag.get("id") == agrup_id
    assert ag.get("nom") == "Activa"
    assert "finalitzada" in ag


def test_agrupar_finalitzada_tambe_bloqueja(client):
    r = client.post("/api/agrupacions", json={
        "nom": "Acabada", "carregues": [_carrega("2026/01/0000888")], "resultat": _resultat(("A",)),
    })
    id_ = r.get_json()["id"]
    client.patch(f"/api/agrupacions/{id_}/producte", json={"art_codi": "A", "preparat": True})
    # Ara és finalitzada però segueix bloquejant
    r = client.post("/api/agrupar", json={"carregues": [_carrega("2026/01/0000888")]})
    assert r.status_code == 409


def test_agrupar_force_no_existeix(client):
    """Verifica que ?force=1 ha estat eliminat com a via per saltar la regla."""
    r = client.post("/api/agrupacions", json={
        "nom": "X", "carregues": [_carrega("2026/01/0000999")], "resultat": _resultat(),
    })
    r = client.post("/api/agrupar?force=1", json={"carregues": [_carrega("2026/01/0000999")]})
    assert r.status_code == 409


def test_agrupar_validacio_400(client):
    r = client.post("/api/agrupar", json={"carregues": []})
    assert r.status_code == 400
    r = client.post("/api/agrupar", json={"carregues": [{"carrega_id": "x"}]})
    # falten camps obligatoris
    assert r.status_code == 400


# --- Pages estàtiques i CSP ---------------------------------------------
def test_index_te_csp_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'self' http://comandes.agrienergia.local " in csp
    assert "http://127.0.0.1:5001" in csp
    assert "http://localhost:5001" in csp
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") is None


def test_magatzem_llista_render(client):
    r = client.get("/magatzem")
    assert r.status_code == 200


def test_magatzem_prep_404_si_no_existeix(client):
    r = client.get("/magatzem/" + "d" * 32)
    assert r.status_code == 404


# --- /api/plantilles ----------------------------------------------------
def test_guardar_amb_plantilla(client):
    r = client.post("/api/agrupacions", json={
        "nom": "Test plantilla",
        "carregues": [{**_carrega(), "tra_codi": "T01", "transportista": "Trans1"}],
        "resultat": _resultat(),
        "plantilla": True,
    })
    assert r.status_code == 200


def test_llistar_plantilles_vacia(client):
    r = client.get("/api/plantilles")
    assert r.status_code == 200
    assert r.get_json() == []


def test_llistar_plantilles_amb_dades(client):
    # 1 sense plantilla, 1 amb
    client.post("/api/agrupacions", json={
        "nom": "Sense",
        "carregues": [_carrega("2026/01/0000001")],
        "resultat": _resultat(),
    })
    client.post("/api/agrupacions", json={
        "nom": "Amb plantilla",
        "carregues": [{**_carrega("2026/01/0000002"), "tra_codi": "T01", "transportista": "T1"}],
        "resultat": _resultat(),
        "plantilla": True,
    })
    r = client.get("/api/plantilles")
    assert r.status_code == 200
    d = r.get_json()
    assert len(d) == 1
    assert d[0]["nom"] == "Amb plantilla"
    assert d[0]["transportistes"][0]["tra_codi"] == "T01"
