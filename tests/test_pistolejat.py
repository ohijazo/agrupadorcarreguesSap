"""Tests dels pendents de pistolejar: el calcul (`dades/pistolejat.py`) i
l'endpoint `/api/pistolejat/pendents`, sense SAP ni PostgreSQL.

Els casos de dades reals (comanda 279 de DB_FARIN_TEST, la paritat SQL/SL)
es comproven amb `scripts/paritat_backends.py --funcio obtenir_dades_pistolejat`.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)

from dades import pistolejat as calc  # noqa: E402


def _carrega(docentry, estat=1, data="2026-10-28", hora="08:00"):
    return {"carrega_id": f"SAP/1/{docentry}", "car_numero": str(docentry),
            "car_descripcion": f"C{docentry}", "car_fecsalida": data,
            "car_fecsalida_hora": hora, "transportista": "T", "car_matricula": "",
            "car_estat": estat}


def _linia(linia, kg=1000.0, kg_oberts=1000.0, sacs=40.0, art="33851", unitat="S25"):
    return {"linia": linia, "art_codi": art, "art_descrip": art, "unitat": unitat,
            "sacs": sacs, "kg": kg, "kg_oberts": kg_oberts}


def _dades(linies, pistolejats=(), carrega=87, docentry=279, estat="CONFIRMADA"):
    return {
        "comandes": [{"docentry": docentry, "docnum": 26600000 + docentry, "carrega": carrega,
                      "cli_codi": "C1", "cli_nom": "Client", "linies": list(linies)}],
        "pistolejats": list(pistolejats),
        "estats": {docentry: estat},
    }


# --- Calcul -------------------------------------------------------------
def test_comanda_279_parcial():
    """El cas real: 1000 kg oberts, 75 kg (3 sacs) pistolejats sense albara."""
    r = calc.construir([_carrega(87)], _dades(
        [_linia(0)], [{"comanda": 279, "linia": 0, "sacs": 3, "kg": 75}]))
    l = r["carregues"][0]["comandes"][0]["linies"][0]
    assert l["kg_pendents"] == 925
    assert l["sacs_oberts"] == 40
    assert l["sacs_pendents"] == 37
    assert l["estat"] == calc.ESTAT_PARCIAL
    assert r["carregues"][0]["comandes"][0]["estat_comanda"] == "CONFIRMADA"


def test_sense_pistolejar_es_pendent_i_completa_desapareix():
    dades = _dades([_linia(0), _linia(1, kg=500, kg_oberts=500, sacs=20)],
                   [{"comanda": 279, "linia": 1, "sacs": 20, "kg": 500}])
    r = calc.construir([_carrega(87)], dades)
    linies = r["carregues"][0]["comandes"][0]["linies"]
    assert [l["linia"] for l in linies] == [0]
    assert linies[0]["estat"] == calc.ESTAT_PENDENT

    r = calc.construir([_carrega(87)], dades, nomes_pendents=False)
    estats = {l["linia"]: l["estat"] for l in r["carregues"][0]["comandes"][0]["linies"]}
    assert estats == {0: calc.ESTAT_PENDENT, 1: calc.ESTAT_COMPLET}
    assert r["totals"]["percent"] == 33   # 500 de 1500 kg


def test_pistolejat_de_mes_no_dona_pendent_negatiu():
    r = calc.construir([_carrega(87)], _dades(
        [_linia(0, kg_oberts=100)], [{"comanda": 279, "linia": 0, "sacs": 10, "kg": 250}]),
        nomes_pendents=False)
    l = r["carregues"][0]["comandes"][0]["linies"][0]
    assert l["kg_pendents"] == 0 and l["sacs_pendents"] == 0
    assert l["estat"] == calc.ESTAT_COMPLET
    assert r["totals"]["percent"] == 100


def test_lectures_de_la_mateixa_linia_se_sumen():
    r = calc.construir([_carrega(87)], _dades([_linia(0)], [
        {"comanda": 279, "linia": 0, "sacs": 10, "kg": 250},
        {"comanda": 279, "linia": 0, "sacs": 10, "kg": 250},
    ]))
    assert r["carregues"][0]["comandes"][0]["linies"][0]["kg_pendents"] == 500


def test_linia_sense_sacs_nomes_te_kg():
    r = calc.construir([_carrega(87)], _dades([_linia(0, sacs=0, unitat="GRA")]))
    l = r["carregues"][0]["comandes"][0]["linies"][0]
    assert l["sacs_oberts"] is None and l["sacs_pendents"] is None
    assert l["kg_pendents"] == 1000


def test_carrega_sortida_nomes_amb_tots():
    dades = _dades([_linia(0)])
    assert calc.construir([_carrega(87, estat=2)], dades)["carregues"] == []
    assert len(calc.construir([_carrega(87, estat=2)], dades, nomes_pendents=False)["carregues"]) == 1


def test_carregues_ordenades_per_sortida_i_sense_comandes_fora():
    dades = {
        "comandes": [
            {"docentry": 1, "docnum": 1, "carrega": 10, "linies": [_linia(0)]},
            {"docentry": 2, "docnum": 2, "carrega": 20, "linies": [_linia(0)]},
        ],
        "pistolejats": [], "estats": {},
    }
    carregues = [_carrega(10, hora="12:00"), _carrega(20, hora="07:30"), _carrega(30)]
    r = calc.construir(carregues, dades)
    assert [c["docentry"] for c in r["carregues"]] == [20, 10]


# --- Endpoint -----------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    import app as app_module
    app_module._rate_buckets.clear()
    with app_module.app.test_client() as c:
        yield c, app_module


def test_endpoint_retorna_el_calcul(client, monkeypatch):
    c, app_module = client
    crides = []

    def fals(desde, fins, nomes_pendents=True):
        crides.append((desde, fins, nomes_pendents))
        return {"carregues": [], "totals": calc._totals([])}

    monkeypatch.setattr(app_module, "llistar_pendents_pistolejar", fals)
    r = c.get("/api/pistolejat/pendents?desde=2026-10-28&fins=2026-10-29")
    assert r.status_code == 200
    assert r.get_json()["carregues"] == []
    r = c.get("/api/pistolejat/pendents?desde=2026-10-28&fins=2026-10-28&tots=1")
    assert crides == [("2026-10-28", "2026-10-29", True), ("2026-10-28", "2026-10-28", False)]


@pytest.mark.parametrize("qs", [
    "",
    "desde=2026-10-28",
    "desde=2026-10-29&fins=2026-10-28",
    "desde=2026-01-01&fins=2026-03-01",
])
def test_endpoint_valida_dates(client, qs):
    c, _ = client
    assert c.get(f"/api/pistolejat/pendents?{qs}").status_code == 400


def test_pagina_no_la_tapa_la_ruta_d_agrupacio(client, monkeypatch):
    """`/magatzem/<id_>` no ha de capturar `/magatzem/pendents`."""
    c, app_module = client
    monkeypatch.setattr(app_module.agrupacions_store, "obtenir",
                        lambda _id: pytest.fail("ha entrat a magatzem_prep"))
    r = c.get("/magatzem/pendents")
    assert r.status_code == 200
    assert b"Pendents de pistolejar" in r.data
