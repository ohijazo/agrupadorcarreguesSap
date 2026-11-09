"""Tests de les etiquetes de palet (`etiquetes.py` i `/api/etiquetes`), sense
SAP ni el motor: es construeix el resultat a mà.

La paritat SQL/SL de les adreces es comprova amb
`scripts/paritat_backends.py --funcio obtenir_adreces_comandes`.
"""
import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)

import etiquetes  # noqa: E402
from models_agrupacio import CarregaResumen, PaletFisic, ResultatAgrupacio  # noqa: E402


def _carrega(num, transportista="Transportes Escapa, S.A."):
    return CarregaResumen(carrega_id=f"SAP/-1/{num}", eje="SAP", sca="-1", car=str(num),
                          tra_codi="T", transportista=transportista, descripcio=f"Carrega {num}")


def _palet(num, comanda, sacs, art="33851"):
    return PaletFisic(carrega_id=f"SAP/-1/{num}", comanda=comanda, tipus_palet="01030",
                      tipus_palet_descrip="PALET EUROPEU", sacs=sacs, articles=[(art, "FARINA", sacs)])


ADRECES = {
    "268/100": {"cli_codi": "C1", "cli_nom": "CAL MOSSO, S.L.", "carrer": "NOU, 16", "poblacio": "PRATS", "cp": "08513"},
    "268/101": {"cli_codi": "C2", "cli_nom": "FORN BO", "carrer": "MAJOR, 1", "poblacio": "VIC", "cp": "08500"},
    "268/102": {"cli_codi": "C1", "cli_nom": "CAL MOSSO, S.L.", "carrer": "NOU, 16", "poblacio": "PRATS", "cp": "08513"},
}


def test_una_etiqueta_per_palet_amb_el_client_i_el_desti():
    r = ResultatAgrupacio(carregues=[_carrega(97)],
                          palets=[_palet(97, "268/100", 32), _palet(97, "268/100", 20), _palet(97, "268/101", 40)])
    out = etiquetes.construir(r, ADRECES)
    assert [c["cli_nom"] for c in out["clients"]] == ["CAL MOSSO, S.L.", "FORN BO"]
    cal = out["clients"][0]
    assert cal["poblacio"] == "PRATS" and cal["carrer"] == "NOU, 16"
    assert cal["n_client"] == 1 and cal["n_palets"] == 2
    assert cal["transportista"] == "Transportes Escapa, S.A." and cal["carrega_num"] == "97"
    assert [(e["palet_n"], e["sacs"]) for e in out["etiquetes"]] == [(1, 32), (2, 20), (1, 40)]


def test_dues_comandes_del_mateix_client_i_adreca_comparteixen_n_client():
    r = ResultatAgrupacio(carregues=[_carrega(97)],
                          palets=[_palet(97, "268/100", 32), _palet(97, "268/101", 40), _palet(97, "268/102", 10)])
    out = etiquetes.construir(r, ADRECES)
    cal = next(c for c in out["clients"] if c["cli_codi"] == "C1")
    assert cal["comandes"] == ["268/100", "268/102"] and cal["n_palets"] == 2 and cal["n_client"] == 1


def test_el_n_client_torna_a_comencar_a_cada_carrega():
    r = ResultatAgrupacio(carregues=[_carrega(97), _carrega(98, "Baldo")],
                          palets=[_palet(97, "268/100", 32), _palet(98, "268/101", 40)])
    out = etiquetes.construir(r, ADRECES)
    assert [(c["carrega_num"], c["n_client"], c["transportista"]) for c in out["clients"]] == [
        ("97", 1, "Transportes Escapa, S.A."), ("98", 1, "Baldo")]


def test_comanda_sense_adreca_no_peta():
    r = ResultatAgrupacio(carregues=[_carrega(97)], palets=[_palet(97, "268/999", 5)])
    out = etiquetes.construir(r, {})
    assert out["clients"][0]["cli_nom"] == "Comanda 268/999" and out["clients"][0]["poblacio"] == ""


def test_api_etiquetes_valida_les_carregues(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    import app as app_module
    with app_module.app.test_client() as c:
        assert c.post("/api/etiquetes", json={"carregues": []}).status_code == 400
        assert c.post("/api/etiquetes", json={}).status_code == 400
