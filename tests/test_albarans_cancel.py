"""Tests de la cancel·lacio d'albarans (`POST /api/albarans/<n>/cancelar`), sense
SAP ni PostgreSQL: es substitueix `escriptura_albarans` per un fals.

La logica del modul de debo (`dades/sl/escriptura_albarans.py`) es prova al
final, nomes si l'app germana hi es (necessita `sap_service_layer`).
"""
import os
import sys
import types

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.modules.setdefault("motor", types.ModuleType("motor"))
_models = types.ModuleType("models")
class _Estat:
    value = "OK"
_models.Estat = _Estat
sys.modules.setdefault("models", _models)


def _estat(**kw):
    e = {"docentry": 148, "docnum": 26700148, "carrega": 98, "usuari": 22,
         "obert": True, "cancelat": False, "linies_tancades": 0}
    e.update(kw)
    return e


class _ErrorSL(Exception):
    def __init__(self, msg, status_code=None, body=None):
        super().__init__(msg)
        self.status_code = status_code
        self.body = body


class _Fals:
    """Substitut de `dades.sl.escriptura_albarans` que apunta les crides."""

    def __init__(self, estat=None, error_cancel=None, error_estat=None):
        self.estat = _estat() if estat is None else estat
        self.error_cancel = error_cancel
        self.error_estat = error_estat
        self.cancelats = []

    def estat_albara(self, doc_entry):
        if self.error_estat:
            raise self.error_estat
        return self.estat or None

    def motiu_no_cancelable(self, estat, usuaris_sga):
        if estat["cancelat"]:
            return "Aquest albarà ja està cancel·lat."
        if estat["usuari"] not in usuaris_sga:
            return "Només els de l'SGA."
        if not estat["obert"] or estat["linies_tancades"]:
            return "Facturat."
        return None

    def cancelar_albara(self, doc_entry):
        if self.error_cancel:
            raise self.error_cancel
        self.cancelats.append(doc_entry)

    def missatge_sap(self, e):
        return ((getattr(e, "body", None) or {}).get("error") or {}).get("message", {}).get("value", "")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("CANCELAR_ALBARANS", "true")
    monkeypatch.setenv("ALBARANS_SGA_USUARIS", "22,23")
    import app as app_module
    app_module._rate_buckets.clear()
    app_module.app.config["CSRF_ENABLED"] = False
    monkeypatch.setattr(app_module, "SLError", _ErrorSL)
    auditats = []
    monkeypatch.setattr(app_module.audit, "log",
                        lambda accio, target=None, detall=None: auditats.append((accio, target, detall)))
    with app_module.app.test_client() as c:
        yield c, app_module, auditats
    app_module.app.config["CSRF_ENABLED"] = True


def _posa(monkeypatch, app_module, fals):
    monkeypatch.setattr(app_module, "escriptura_albarans", fals)
    return fals


def _cancela(c, motiu="Lot equivocat", n=148):
    return c.post(f"/api/albarans/{n}/cancelar", json={"motiu": motiu})


def test_cancela_i_audita_amb_motiu(client, monkeypatch):
    c, app_module, auditats = client
    fals = _posa(monkeypatch, app_module, _Fals())
    r = _cancela(c, "  Lot   equivocat  ")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "docnum": 26700148}
    assert fals.cancelats == [148]
    assert auditats == [("cancelar_albara", "26700148",
                         {"docentry": 148, "carrega": 98, "motiu": "Lot equivocat"})]


def test_apagat_per_defecte(client, monkeypatch):
    c, app_module, auditats = client
    monkeypatch.delenv("CANCELAR_ALBARANS")
    fals = _posa(monkeypatch, app_module, _Fals())
    assert _cancela(c).status_code == 404
    assert fals.cancelats == [] and auditats == []


def test_sense_app_germana_no_disponible(client, monkeypatch):
    c, app_module, _ = client
    _posa(monkeypatch, app_module, None)
    assert _cancela(c).status_code == 503


@pytest.mark.parametrize("motiu", [None, "", "    ", "abc", "x" * 201])
def test_motiu_obligatori(client, monkeypatch, motiu):
    c, app_module, _ = client
    fals = _posa(monkeypatch, app_module, _Fals())
    assert _cancela(c, motiu).status_code == 400
    assert fals.cancelats == []


def test_albara_inexistent(client, monkeypatch):
    c, app_module, _ = client
    fals = _posa(monkeypatch, app_module, _Fals(estat={}))
    assert _cancela(c).status_code == 404
    assert fals.cancelats == []


@pytest.mark.parametrize("estat", [
    _estat(cancelat=True),
    _estat(usuari=1),
    _estat(obert=False),
    _estat(linies_tancades=1),
])
def test_no_cancelable_no_arriba_a_sap(client, monkeypatch, estat):
    c, app_module, auditats = client
    fals = _posa(monkeypatch, app_module, _Fals(estat=estat))
    r = _cancela(c)
    assert r.status_code == 409
    assert fals.cancelats == [] and auditats == []


def test_usuaris_sga_configurables(client, monkeypatch):
    c, app_module, _ = client
    monkeypatch.setenv("ALBARANS_SGA_USUARIS", "30")
    fals = _posa(monkeypatch, app_module, _Fals(estat=_estat(usuari=30)))
    assert _cancela(c).status_code == 200
    assert fals.cancelats == [148]


def test_sap_rebutja_ensenya_el_missatge_i_audita_l_error(client, monkeypatch):
    c, app_module, auditats = client
    body = {"error": {"code": -5002, "message": {"value": "Document bloquejat per l'SGA"}}}
    _posa(monkeypatch, app_module, _Fals(error_cancel=_ErrorSL("400", 400, body)))
    r = _cancela(c)
    assert r.status_code == 409
    assert "Document bloquejat per l'SGA" in r.get_json()["error"]
    assert auditats[0][0] == "cancelar_albara_error"
    assert auditats[0][2]["error"] == "Document bloquejat per l'SGA"


def test_sap_caigut_en_cancel_lar(client, monkeypatch):
    c, app_module, auditats = client
    _posa(monkeypatch, app_module, _Fals(error_cancel=_ErrorSL("5xx", 502)))
    r = _cancela(c)
    assert r.status_code == 503
    assert "502" not in r.get_json()["error"]
    assert [a[0] for a in auditats] == ["cancelar_albara_error"]


def test_sap_caigut_en_llegir(client, monkeypatch):
    c, app_module, auditats = client
    fals = _posa(monkeypatch, app_module, _Fals(error_estat=requests.ConnectionError("x")))
    assert _cancela(c).status_code == 503
    assert fals.cancelats == [] and auditats == []


def test_demana_csrf(client, monkeypatch):
    c, app_module, _ = client
    app_module.app.config["CSRF_ENABLED"] = True
    fals = _posa(monkeypatch, app_module, _Fals())
    assert _cancela(c).status_code == 403
    assert fals.cancelats == []


def test_llista_marca_els_cancelables(client, monkeypatch):
    c, app_module, _ = client
    alb = lambda **kw: {"docentry": 1, "usuari": 22, "obert": True, "cancelat": False, **kw}
    monkeypatch.setattr(app_module, "llistar_albarans_carregues", lambda ids: [
        alb(), alb(usuari=12), alb(obert=False), alb(cancelat=True)])
    j = c.get("/api/albarans?carregues=98").get_json()
    assert j["cancelar"] is True
    assert [a["cancelable"] for a in j["albarans"]] == [True, False, False, False]
    monkeypatch.setenv("CANCELAR_ALBARANS", "false")
    j = c.get("/api/albarans?carregues=98").get_json()
    assert j["cancelar"] is False and not any(a["cancelable"] for a in j["albarans"])


# --- Modul de debo ------------------------------------------------------
@pytest.fixture
def esc(monkeypatch):
    pytest.importorskip("sap_service_layer")
    from dades.sl import escriptura_albarans as m
    return m


def test_motiu_no_cancelable(esc):
    assert esc.motiu_no_cancelable(_estat(), {22}) is None
    assert "ja està cancel·lat" in esc.motiu_no_cancelable(_estat(cancelat=True), {22})
    assert "SGA" in esc.motiu_no_cancelable(_estat(usuari=1), {22})
    assert "facturat" in esc.motiu_no_cancelable(_estat(linies_tancades=2), {22})


def test_cancel_amb_error_pero_ja_cancel_lat_es_ok(esc, monkeypatch):
    class _C:
        def _request(self, *a, **k):
            raise requests.ReadTimeout("timeout")
    monkeypatch.setattr(esc, "client", lambda: _C())
    monkeypatch.setattr(esc, "estat_albara", lambda n: _estat(cancelat=True))
    esc.cancelar_albara(148)  # no llença


def test_cancel_amb_error_i_no_cancel_lat_propaga(esc, monkeypatch):
    class _C:
        def _request(self, *a, **k):
            raise esc.SLError("rebutjat", status_code=400)
    monkeypatch.setattr(esc, "client", lambda: _C())
    monkeypatch.setattr(esc, "estat_albara", lambda n: _estat())
    with pytest.raises(esc.SLError):
        esc.cancelar_albara(148)


def test_missatge_sap(esc):
    e = esc.SLError("x", status_code=400, body={"error": {"message": {"value": " No es pot "}}})
    assert esc.missatge_sap(e) == "No es pot"
    assert esc.missatge_sap(esc.SLError("x")) == ""
