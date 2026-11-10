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
    assert b"Pendents del dia" in r.data


# --- Progres d'una agrupacio (substitueix el checklist manual) -------------
def _resultat(*productes):
    """`productes`: (art_codi, [docentry de carrega, ...])."""
    return {"productes": [
        {"art_codi": art, "per_carrega": [{"carrega_id": f"SAP/1/{c}"} for c in cars]}
        for art, cars in productes]}


def _dues_comandes(l87, l98, pist=()):
    return {
        "comandes": [
            {"docentry": 279, "docnum": 1, "carrega": 87, "cli_codi": "C1", "cli_nom": "", "linies": l87},
            {"docentry": 330, "docnum": 2, "carrega": 98, "cli_codi": "C2", "cli_nom": "", "linies": l98},
        ],
        "pistolejats": list(pist),
        "estats": {},
    }


def test_progres_res_pistolejat_es_pendent():
    r = calc.progres_agrupacio(_resultat(("33851", [87])), _dades([_linia(0)]))
    p = r["productes"]["33851"]
    assert p["estat"] == "pendent" and p["kg_fets"] == 0 and p["sacs_total"] == 40
    assert r["fets"] == [] and r["n_productes"] == 1 and r["percent"] == 0


def test_progres_parcial_i_complet_pel_pistolejat():
    res = _resultat(("33851", [87]))
    p = calc.progres_agrupacio(res, _dades([_linia(0)], [{"comanda": 279, "linia": 0, "sacs": 10, "kg": 250}]))
    assert p["productes"]["33851"]["estat"] == "parcial"
    assert p["productes"]["33851"]["sacs_fets"] == 10 and p["percent"] == 25
    p = calc.progres_agrupacio(res, _dades([_linia(0)], [{"comanda": 279, "linia": 0, "sacs": 40, "kg": 1000}]))
    assert p["fets"] == ["33851"] and p["percent"] == 100


def test_progres_linia_amb_albara_es_feta():
    # Linia tancada: l'albara ja ha descomptat l'OpenInvQty i la lectura ja
    # no compta (te TargetEntry), aixi que no arriba com a pistolejat.
    r = calc.progres_agrupacio(_resultat(("33851", [87])), _dades([_linia(0, kg_oberts=0)]))
    assert r["productes"]["33851"]["estat"] == "complet" and r["fets"] == ["33851"]


def test_progres_albara_cancel_lat_torna_a_pendent():
    # Albara cancel·lat: la linia es reobre sencera i la lectura apunta a
    # l'albara cancel·lat (tampoc no arriba). Ha de tornar a sortir pendent.
    r = calc.progres_agrupacio(_resultat(("33851", [87])), _dades([_linia(0)]))
    assert r["productes"]["33851"]["estat"] == "pendent"


def test_progres_mateix_article_a_dues_carregues():
    res = _resultat(("33851", [87, 98]))
    r = calc.progres_agrupacio(res, _dues_comandes([_linia(0, kg_oberts=0)], [_linia(0)]))
    p = r["productes"]["33851"]
    assert p["estat"] == "parcial" and p["kg_total"] == 2000 and p["kg_fets"] == 1000
    assert p["per_carrega"]["SAP/1/87"]["estat"] == "complet"
    assert p["per_carrega"]["SAP/1/98"]["estat"] == "pendent"
    assert r["fets"] == []


def test_progres_article_d_una_altra_carrega_no_compta():
    # L'article 33851 de la carrega 98 no es d'aquest producte (nomes a la 87).
    r = calc.progres_agrupacio(_resultat(("33851", [87])),
                               _dues_comandes([_linia(0, kg_oberts=0)], [_linia(0)]))
    assert r["fets"] == ["33851"]


def test_progres_producte_sense_dades_compta_com_a_fet():
    # Comanda cancel·lada o moguda: no queda res per carregar. Si no comptes
    # com a fet, l'agrupacio no s'acabaria mai sola.
    r = calc.progres_agrupacio(_resultat(("33851", [87]), ("99999", [87])),
                               _dades([_linia(0, kg_oberts=0)]))
    assert r["productes"]["99999"]["estat"] == "sense_dades"
    assert r["fets"] == ["33851", "99999"] and r["n_productes"] == 2
    assert r["percent"] == 100


def test_progres_carrega_sense_dades_no_bloqueja_el_producte():
    # La 98 ja no te la comanda; la 87 esta entregada: el producte es fet.
    r = calc.progres_agrupacio(_resultat(("33851", [87, 98])), _dades([_linia(0, kg_oberts=0)]))
    p = r["productes"]["33851"]
    assert p["per_carrega"]["SAP/1/98"]["estat"] == "sense_dades"
    assert r["fets"] == ["33851"]


def test_progres_no_diu_100_si_falta_algun_producte():
    # 99,9% dels kg fets pero un producte petit encara pendent.
    linies = [_linia(0, kg=100000, kg_oberts=0), _linia(1, kg=50, kg_oberts=50, art="01010")]
    r = calc.progres_agrupacio(_resultat(("33851", [87]), ("01010", [87])), _dades(linies))
    assert r["fets"] == ["33851"] and r["percent"] == 99


def test_progres_granel_sense_sacs():
    r = calc.progres_agrupacio(_resultat(("33851", [87])), _dades([_linia(0, sacs=0)]))
    assert r["productes"]["33851"]["sacs_total"] is None


# --- Cache del progres (diverses tablets, una consulta a SAP) --------------
def test_progres_amb_cache_reaprofita_uns_segons(monkeypatch):
    import preparacio_sga
    crides = []
    monkeypatch.setattr(preparacio_sga, "progres_i_sincronitza",
                        lambda obj: crides.append(obj["id"]) or {"fets": [], "id": obj["id"]})
    monkeypatch.setattr(preparacio_sga, "_cache", {})
    rellotge = [1000.0]
    monkeypatch.setattr(preparacio_sga.time, "monotonic", lambda: rellotge[0])
    a, b = {"id": "a" * 32}, {"id": "b" * 32}
    preparacio_sga.progres_amb_cache(a)
    preparacio_sga.progres_amb_cache(a)
    preparacio_sga.progres_amb_cache(b)
    assert crides == ["a" * 32, "b" * 32]
    rellotge[0] += preparacio_sga.CACHE_S + 1
    preparacio_sga.progres_amb_cache(a)
    assert crides == ["a" * 32, "b" * 32, "a" * 32]


# --- Pendents del dia: a quina agrupacio es cada carrega -----------------
def test_pendents_diu_l_agrupacio_o_sense_agrupar(monkeypatch):
    import app as app_module
    index = {
        "SAP/1/87": [{"id": "vella", "nom": "Tancada", "finalitzada": True},
                     {"id": "viva", "nom": "Escapa dimarts", "finalitzada": False}],
        "SAP/1/98": [{"id": "acabada", "nom": "Baldo", "finalitzada": True}],
    }
    monkeypatch.setattr(app_module.agrupacions_store, "index_carregues_agrupades", lambda: index)
    carregues = [{"carrega_id": "SAP/1/87"}, {"carrega_id": "SAP/1/98"}, {"carrega_id": "SAP/1/99"}]
    app_module._afegeix_agrupacio(carregues)
    assert carregues[0]["agrupacio"] == {"id": "viva", "nom": "Escapa dimarts"}
    assert carregues[1]["agrupacio"] == {"id": "acabada", "nom": "Baldo"}
    assert carregues[2]["agrupacio"] is None


def test_pendents_sense_postgres_no_posa_etiqueta(monkeypatch):
    import app as app_module

    def falla():
        raise RuntimeError("PG caigut")
    monkeypatch.setattr(app_module.agrupacions_store, "index_carregues_agrupades", falla)
    carregues = [{"carrega_id": "SAP/1/87"}]
    app_module._afegeix_agrupacio(carregues)
    assert "agrupacio" not in carregues[0]


# --- Lectures d'un albara cancel·lat: avis, sense restar del pendent ------
def _cancelats(kg=250.0, sacs=10.0, docnum=26700148, comanda=279, linia=0):
    return [{"comanda": comanda, "linia": linia, "albara": 148, "docnum": docnum, "sacs": sacs, "kg": kg}]


def test_pendents_avisa_de_lectures_d_albara_cancel_lat():
    d = _dades([_linia(0), _linia(1, art="30350")])
    d["pistolejats_cancelats"] = _cancelats()
    r = calc.construir([_carrega(87)], d, nomes_pendents=False)
    l0, l1 = r["carregues"][0]["comandes"][0]["linies"]
    assert l0["cancelat"] == {"kg": 250.0, "sacs": 10.0, "albarans": [26700148]}
    assert l0["estat"] == "pendent" and l0["kg_pendents"] == 1000  # no resta del pendent
    assert l1["cancelat"] is None


def test_preparacio_avisa_per_producte_i_per_carrega():
    d = _dades([_linia(0)])
    d["pistolejats_cancelats"] = _cancelats()
    p = calc.progres_agrupacio(_resultat(("33851", [87])), d)["productes"]["33851"]
    assert p["estat"] == "pendent" and p["kg_fets"] == 0
    assert p["cancelat"] == {"kg": 250.0, "albarans": [26700148]}
    assert p["per_carrega"]["SAP/1/87"]["cancelat"] == {"kg": 250.0, "albarans": [26700148]}


def test_sense_lectures_cancel_lades_no_hi_ha_avis():
    p = calc.progres_agrupacio(_resultat(("33851", [87])), _dades([_linia(0)]))["productes"]["33851"]
    assert p["cancelat"] is None


# --- Granel (propietat 5 "Es Granel" o unitat GRA): en kg, mai en sacs ------
def test_granel_no_te_sacs():
    # Cas real: comanda 26600263, 01921 ESPECIFICA VIENA, PackQty = 10000 (kg).
    l = _linia(0, kg=10000, kg_oberts=10000, sacs=10000, art="01921", unitat="GRA")
    l["granel"] = True
    r = calc.construir([_carrega(87)], _dades([l]), nomes_pendents=False)
    lc = r["carregues"][0]["comandes"][0]["linies"][0]
    assert lc["granel"] is True and lc["sacs_pendents"] is None and lc["kg_pendents"] == 10000


def test_granel_a_la_preparacio_no_suma_sacs():
    l = _linia(0, kg=10000, kg_oberts=10000, sacs=10000, art="01921", unitat="KG")
    l["granel"] = True   # propietat 5 encara que la unitat no sigui GRA
    p = calc.progres_agrupacio(_resultat(("01921", [87])), _dades([l]))["productes"]["01921"]
    assert p["sacs_total"] is None and p["kg_total"] == 10000
