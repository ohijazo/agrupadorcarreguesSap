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


def test_comanda_amb_albara_no_es_pendent():
    # Un sol albara per comanda: amb albara (parcial) ja no surt a pendents,
    # encara que li quedin linies obertes. Si es mostra tot, porta l'albara.
    dades = _dades([_linia(0), _linia(1)])
    dades["albarans"] = [{"comanda": 279, "albara": 900, "docnum": 7001}]
    assert calc.construir([_carrega(87)], dades)["carregues"] == []
    r = calc.construir([_carrega(87)], dades, nomes_pendents=False)
    assert r["carregues"][0]["comandes"][0]["albarans"] == [7001]


def test_comanda_sense_albara_porta_llista_buida():
    r = calc.construir([_carrega(87)], _dades([_linia(0)]))
    assert r["carregues"][0]["comandes"][0]["albarans"] == []


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
    app_module._cache_pendents.clear()
    app_module._cache_pist_carregues.clear()
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
    assert "Preparació de comanda" in r.get_data(as_text=True)


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


# --- Preparació de comanda: a quina agrupacio es cada carrega -----------------
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


# --- Cache de "Preparacio de comanda" --------------------------------------
def test_endpoint_reaprofita_el_resultat_uns_segons(client, monkeypatch):
    c, app_module = client
    crides = []
    monkeypatch.setattr(app_module, "llistar_pendents_pistolejar",
                        lambda d, f, nomes_pendents=True: crides.append(1) or
                        {"carregues": [], "totals": calc._totals([])})
    url = "/api/pistolejat/pendents?desde=2026-10-28&fins=2026-10-29"
    assert c.get(url).status_code == 200
    assert c.get(url).status_code == 200
    assert len(crides) == 1
    assert c.get(url + "&tots=1").status_code == 200   # una altra clau
    assert len(crides) == 2


def test_pendents_demana_capcaleres_sense_derivats(monkeypatch):
    import consultes_carregues as cc
    rebut = {}

    def llistar(desde, fins, **kw):
        rebut.update(kw)
        return {"items": [_carrega(87)]}

    monkeypatch.setattr(cc, "llistar_carregues", llistar)
    monkeypatch.setattr(cc, "obtenir_dades_pistolejat", lambda ids, **kw: _dades([_linia(0)]))
    r = cc.llistar_pendents_pistolejar("2026-10-28", "2026-10-28")
    assert rebut == {"limit": 1000, "derivats": False}
    assert r["carregues"][0]["docentry"] == 87


# --- % pistolejat per carrega (pagina principal) ---------------------------
def test_progres_per_carrega_parcial_complet_i_amb_albara():
    dades = {
        "comandes": [
            # 87: 1000 kg, 250 pistolejats -> 25%
            {"docentry": 279, "docnum": 1, "carrega": 87, "cli_codi": "C1", "cli_nom": "",
             "linies": [_linia(0)]},
            # 98: una linia amb albara (oberta 0) i una de pistolejada sencera -> complet
            {"docentry": 330, "docnum": 2, "carrega": 98, "cli_codi": "C2", "cli_nom": "",
             "linies": [_linia(0, kg_oberts=0), _linia(1, kg=500, kg_oberts=500, sacs=20)]},
            # 99: res -> pendent
            {"docentry": 331, "docnum": 3, "carrega": 99, "cli_codi": "C3", "cli_nom": "",
             "linies": [_linia(0)]},
        ],
        "pistolejats": [{"comanda": 279, "linia": 0, "sacs": 10, "kg": 250},
                        {"comanda": 330, "linia": 1, "sacs": 20, "kg": 500}],
        "estats": {},
    }
    r = calc.progres_per_carrega(dades)
    assert r[87] == {"estat": "parcial", "percent": 25, "kg_total": 1000, "kg_fets": 250,
                     "n_comandes": 1, "comandes_albara": []}
    assert r[98]["estat"] == "complet" and r[98]["percent"] == 100
    assert r[99]["estat"] == "pendent" and r[99]["percent"] == 0


def test_progres_per_carrega_comandes_amb_albara():
    dades = {
        "comandes": [
            {"docentry": 1, "docnum": 501, "carrega": 87, "linies": [_linia(0)]},
            {"docentry": 2, "docnum": 502, "carrega": 87, "linies": [_linia(0, kg_oberts=0)]},
            {"docentry": 3, "docnum": 503, "carrega": 87, "linies": [_linia(0)]},
        ],
        "pistolejats": [], "estats": {},
        "albarans": [{"comanda": 2, "albara": 900, "docnum": 7001}],
    }
    r = calc.progres_per_carrega(dades)
    assert r[87]["n_comandes"] == 3
    assert r[87]["comandes_albara"] == [502]


def test_progres_per_carrega_no_arrodoneix_a_100_si_falta():
    r = calc.progres_per_carrega(_dades([_linia(0)], [{"comanda": 279, "linia": 0, "sacs": 39.9, "kg": 998}]))
    assert r[87]["estat"] == "parcial" and r[87]["percent"] == 99


def test_endpoint_pistolejat_carregues(client, monkeypatch):
    c, app_module = client
    crides = []
    monkeypatch.setattr(app_module, "progres_carregues",
                        lambda ids: crides.append(ids) or {87: {"estat": "parcial", "percent": 25,
                                                               "kg_total": 1000, "kg_fets": 250}})
    r = c.get("/api/pistolejat/carregues?ids=98,87,87")
    assert r.status_code == 200
    assert r.get_json() == {"carregues": {"87": {"estat": "parcial", "percent": 25,
                                                 "kg_total": 1000, "kg_fets": 250}}}
    assert crides == [[87, 98]]
    c.get("/api/pistolejat/carregues?ids=87,98")       # mateix conjunt: cache
    assert len(crides) == 1
    assert c.get("/api/pistolejat/carregues?ids=").get_json() == {"carregues": {}}


@pytest.mark.parametrize("qs", ["ids=abc", "ids=1,-2",
                                "ids=" + ",".join(str(i) for i in range(1, 302))])
def test_endpoint_pistolejat_carregues_valida(client, monkeypatch, qs):
    c, app_module = client
    monkeypatch.setattr(app_module, "progres_carregues", lambda ids: pytest.fail("no s'havia de consultar SAP"))
    assert c.get(f"/api/pistolejat/carregues?{qs}").status_code == 400


def test_pistolejat_carregues_no_es_public(client, monkeypatch):
    """`/api/carregues` es public (calendari); aquesta ruta no hi ha de penjar."""
    c, app_module = client
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(app_module, "progres_carregues", lambda ids: pytest.fail("sense sessio"))
    r = c.get("/api/pistolejat/carregues?ids=87")
    assert r.status_code in (302, 401)


# --- Lots pistolejats a "Preparacio de comanda" ----------------------------
def test_lots_per_linia_primer_els_d_albara():
    dades = _dades([_linia(0), _linia(1)])
    dades["lots"] = [
        {"comanda": 279, "linia": 0, "lot": "26010320", "albara": False, "sacs": 10, "kg": 250},
        {"comanda": 279, "linia": 0, "lot": "26010318", "albara": True, "sacs": 20, "kg": 500},
    ]
    r = calc.construir([_carrega(87)], dades, nomes_pendents=False)
    linies = r["carregues"][0]["comandes"][0]["linies"]
    assert [x["lot"] for x in linies[0]["lots"]] == ["26010318", "26010320"]
    assert linies[0]["lots"][0] == {"lot": "26010318", "kg": 500, "sacs": 20, "albara": True}
    assert linies[1]["lots"] == []


def test_sense_lots_llegits_la_linia_no_en_porta():
    r = calc.construir([_carrega(87)], _dades([_linia(0)]))
    assert "lots" not in r["carregues"][0]["comandes"][0]["linies"][0]


# --- Calendari (public) ----------------------------------------------------
def _progres_87(ids):
    return {87: {"estat": "parcial", "percent": 25, "kg_total": 1000, "kg_fets": 250,
                 "n_comandes": 3, "comandes_albara": [502]}}


def test_calendari_pistolejat_public_i_sense_kg(client, monkeypatch):
    c, app_module = client
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(app_module, "progres_carregues", _progres_87)
    r = c.get("/api/carregues/pistolejat?ids=87")      # sense sessio
    assert r.status_code == 200
    assert r.get_json() == {"carregues": {"87": {"estat": "parcial", "percent": 25,
                                                 "n_comandes": 3, "comandes_albara": [502]}}}


def test_calendari_pistolejat_comparteix_cache(client, monkeypatch):
    c, app_module = client
    crides = []
    monkeypatch.setattr(app_module, "progres_carregues", lambda ids: crides.append(ids) or _progres_87(ids))
    c.get("/api/pistolejat/carregues?ids=87")
    c.get("/api/carregues/pistolejat?ids=87")
    assert len(crides) == 1


@pytest.mark.parametrize("qs", ["ids=abc", "ids=" + ",".join(str(i) for i in range(1, 302))])
def test_calendari_pistolejat_valida(client, monkeypatch, qs):
    c, app_module = client
    monkeypatch.setattr(app_module, "progres_carregues", lambda ids: pytest.fail("no s'havia de consultar SAP"))
    assert c.get(f"/api/carregues/pistolejat?{qs}").status_code == 400


def test_calendari_pistolejat_limit_de_crides(client, monkeypatch):
    c, app_module = client
    monkeypatch.setattr(app_module, "progres_carregues", _progres_87)
    codis = [c.get("/api/carregues/pistolejat?ids=87").status_code for _ in range(31)]
    assert codis[:30] == [200] * 30 and codis[30] == 429
