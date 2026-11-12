"""Tests de la cancel·lacio d'albarans (`POST /api/albarans/<n>/cancelar`), sense
SAP ni PostgreSQL: es substitueix `escriptura_albarans` per un fals.

La logica del modul de debo (`dades/sl/escriptura_albarans.py`) es prova al
final, nomes si l'app germana hi es (necessita `sap_service_layer`).
"""
import contextlib
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
    # Sense PostgreSQL: el bloqueig per albara (advisory lock) es fals i
    # apunta quins albarans s'han bloquejat.
    app_module._bloquejats = []

    @contextlib.contextmanager
    def bloqueig(doc_entry):
        app_module._bloquejats.append(doc_entry)
        yield
    monkeypatch.setattr(app_module, "_bloqueig_albara", bloqueig)
    auditats = []
    monkeypatch.setattr(app_module.audit, "log",
                        lambda accio, target=None, detall=None: auditats.append((accio, target, detall)))
    # Sense PostgreSQL: qui ha cancel·lat es desa en una llista.
    app_module._desats = []
    monkeypatch.setattr(app_module, "_desa_cancelat",
                        lambda *a: app_module._desats.append(a))
    with app_module.app.test_client() as c:
        yield c, app_module, auditats
    app_module.app.config["CSRF_ENABLED"] = True


def _posa(monkeypatch, app_module, fals):
    monkeypatch.setattr(app_module, "escriptura_albarans", fals)
    return fals


def _cancela(c, motiu="Lot equivocat", n=148, codi="193"):
    return c.post(f"/api/albarans/{n}/cancelar", json={"codi": codi, "motiu": motiu})


def test_cancela_i_audita_amb_motiu(client, monkeypatch):
    c, app_module, auditats = client
    fals = _posa(monkeypatch, app_module, _Fals())
    r = _cancela(c, "  Lot   equivocat  ")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "docnum": 26700148, "operari": "Abdelkrim Fahchouch"}
    assert fals.cancelats == [148]
    assert auditats == [("cancelar_albara", "26700148",
                         {"docentry": 148, "carrega": 98, "motiu": "Lot equivocat",
                          "operari": "Abdelkrim Fahchouch"})]
    assert app_module._desats == [(148, 26700148, "Abdelkrim Fahchouch", "Lot equivocat")]
    # El codi de l'operari no surt enlloc: ni a la resposta ni a l'auditoria.
    assert "193" not in r.get_data(as_text=True)
    assert "193" not in repr(auditats) + repr(app_module._desats)
    # La comprovacio i el POST van dins del bloqueig d'aquest albara.
    assert app_module._bloquejats == [148]


def test_sense_bloqueig_no_cancel_la(client, monkeypatch):
    # Si PostgreSQL no respon no podem garantir una sola cancel·lacio entre
    # els dos workers: no es crida SAP.
    import psycopg
    c, app_module, auditats = client
    fals = _posa(monkeypatch, app_module, _Fals())

    @contextlib.contextmanager
    def sense_pg(doc_entry):
        raise psycopg.OperationalError("PG caigut")
        yield
    monkeypatch.setattr(app_module, "_bloqueig_albara", sense_pg)
    r = _cancela(c)
    assert r.status_code == 503
    assert fals.cancelats == [] and auditats == []


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


@pytest.mark.parametrize("codi", [None, "", "   ", "999", "abc", "19 3", "-193", "1930000000"])
def test_codi_operari_no_valid(client, monkeypatch, codi):
    c, app_module, auditats = client
    fals = _posa(monkeypatch, app_module, _Fals())
    r = _cancela(c, codi=codi)
    assert r.status_code == 403
    assert fals.cancelats == [] and auditats == [] and app_module._desats == []
    assert app_module._bloquejats == []


def test_codi_amb_espais_i_numeric(client, monkeypatch):
    c, app_module, _ = client
    fals = _posa(monkeypatch, app_module, _Fals())
    assert _cancela(c, codi=" 226 ").status_code == 200
    assert _cancela(c, codi=127).status_code == 200
    assert [d[2] for d in app_module._desats] == ["Oussama Aknaf", "Joan Ballesteros Solbes"]
    assert fals.cancelats == [148, 148]


def test_codis_errats_frenats_pel_rate_limit(client, monkeypatch):
    c, app_module, _ = client
    _posa(monkeypatch, app_module, _Fals())
    codis = [_cancela(c, codi=str(n)).status_code for n in range(100, 112)]
    assert codis[:10] == [403] * 10 and codis[10:] == [429, 429]


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
    assert app_module._desats == []


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
    monkeypatch.setattr(app_module, "llistar_albarans_dates", lambda d, f, u: [
        alb(), alb(usuari=12), alb(obert=False), alb(cancelat=True)])
    j = c.get("/api/albarans?desde=2026-11-09&fins=2026-11-09").get_json()
    assert j["cancelar"] is True
    assert [a["cancelable"] for a in j["albarans"]] == [True, False, False, False]
    monkeypatch.setenv("CANCELAR_ALBARANS", "false")
    j = c.get("/api/albarans?desde=2026-11-09&fins=2026-11-09").get_json()
    assert j["cancelar"] is False and not any(a["cancelable"] for a in j["albarans"])


def test_llista_diu_qui_ha_cancel_lat(client, monkeypatch):
    import db
    c, app_module, _ = client
    monkeypatch.setattr(app_module, "llistar_albarans_dates", lambda d, f, u: [
        {"docentry": 1, "usuari": 22, "obert": True, "cancelat": False},
        {"docentry": 2, "usuari": 22, "obert": True, "cancelat": True},
        {"docentry": 3, "usuari": 22, "obert": True, "cancelat": True}])
    demanats = []

    def fetch_all(sql, params):
        demanats.append(params[0])
        return [{"docentry": 2, "operari_nom": "Adil Ennali"}]
    monkeypatch.setattr(db, "fetch_all", fetch_all)
    j = c.get("/api/albarans?desde=2026-11-09&fins=2026-11-09").get_json()
    assert demanats == [[2, 3]]   # només es busquen els cancel·lats
    assert [a.get("cancelat_per") for a in j["albarans"]] == [None, "Adil Ennali", None]


def test_llista_sense_pg_surt_igual(client, monkeypatch):
    import db
    c, app_module, _ = client
    monkeypatch.setattr(app_module, "llistar_albarans_dates", lambda d, f, u: [
        {"docentry": 2, "usuari": 22, "obert": False, "cancelat": True}])

    def caigut(*a, **k):
        raise RuntimeError("PG caigut")
    monkeypatch.setattr(db, "fetch_all", caigut)
    r = c.get("/api/albarans?desde=2026-11-09&fins=2026-11-09")
    assert r.status_code == 200
    assert "cancelat_per" not in r.get_json()["albarans"][0]


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


def test_magatzem_no_pot_cancel_lar(client, monkeypatch):
    c, app_module, auditats = client
    monkeypatch.setenv("AUTH_ENABLED", "true")
    fals = _posa(monkeypatch, app_module, _Fals())
    with c.session_transaction() as sess:
        sess.update(user_id=1, user_name="Prova", user_username="prova@pytest.local", user_rol="magatzem")
    assert _cancela(c).status_code == 403
    assert fals.cancelats == [] and auditats == []
