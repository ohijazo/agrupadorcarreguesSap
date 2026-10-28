"""Tests de la impressio d'albarans: `/api/albarans` i el proxy
`/albarans/<docentry>/pdf` cap al servei `serveis/crystal-pdf`, sense SAP, sense
PostgreSQL i sense el servei (es mockeja `requests.get`).

La paritat SQL/SL de `llistar_albarans_carregues` es comprova amb
`scripts/paritat_backends.py --funcio llistar_albarans_carregues`.
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

PDF = b"%PDF-1.7 fals"


class _Resp:
    def __init__(self, status=200, content=PDF, ctype="application/pdf", docnum="26700148"):
        self.status_code = status
        self.content = content
        self.text = content.decode("latin-1")
        self.headers = {"Content-Type": ctype}
        if docnum is not None:
            self.headers["X-DocNum"] = docnum


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("CRYSTAL_PDF_URL", "http://sap:8095/")
    monkeypatch.setenv("CRYSTAL_PDF_TOKEN", "t" * 32)
    import app as app_module
    app_module._rate_buckets.clear()
    auditats = []
    monkeypatch.setattr(app_module.audit, "log",
                        lambda accio, target=None, detall=None: auditats.append((accio, target, detall)))
    with app_module.app.test_client() as c:
        yield c, app_module, auditats


def _mock_get(monkeypatch, app_module, resposta):
    crides = []

    def fals(url, params=None, headers=None, timeout=None):
        crides.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(app_module.requests, "get", fals)
    return crides


# --- PDF ----------------------------------------------------------------
def test_pdf_ok_passa_token_i_audita(client, monkeypatch):
    c, app_module, auditats = client
    crides = _mock_get(monkeypatch, app_module, _Resp())
    r = c.get("/albarans/148/pdf")
    assert r.status_code == 200
    assert r.data == PDF
    assert r.headers["Content-Type"] == "application/pdf"
    assert r.headers["Content-Disposition"] == 'inline; filename="Albara_26700148.pdf"'
    assert r.headers["Cache-Control"] == "no-store"
    assert crides == [{"url": "http://sap:8095/pdf", "params": {"tipus": "DLN2", "docentry": 148},
                       "headers": {"X-Token": "t" * 32}, "timeout": 60}]
    assert auditats == [("imprimir_albara", "26700148", {"docentry": 148})]


def test_pdf_docnum_estrany_no_entra_a_la_capcalera(client, monkeypatch):
    c, app_module, _ = client
    _mock_get(monkeypatch, app_module, _Resp(docnum='1"; x=y'))
    r = c.get("/albarans/148/pdf")
    assert r.headers["Content-Disposition"] == 'inline; filename="Albara_148.pdf"'


def test_pdf_apagat_sense_url(client, monkeypatch):
    c, app_module, auditats = client
    monkeypatch.setenv("CRYSTAL_PDF_URL", "")
    crides = _mock_get(monkeypatch, app_module, _Resp())
    r = c.get("/albarans/148/pdf")
    assert r.status_code == 404
    assert "no està activada" in r.get_data(as_text=True)
    assert crides == [] and auditats == []


def test_pdf_servei_caigut(client, monkeypatch):
    c, app_module, auditats = client
    _mock_get(monkeypatch, app_module, requests.ConnectionError("refused"))
    r = c.get("/albarans/148/pdf")
    assert r.status_code == 503
    assert r.headers["Content-Type"].startswith("text/plain")
    assert auditats == []


def test_pdf_albara_inexistent(client, monkeypatch):
    c, app_module, auditats = client
    _mock_get(monkeypatch, app_module, _Resp(404, b"no existeix", "text/plain", None))
    r = c.get("/albarans/999999/pdf")
    assert r.status_code == 404
    assert "no existeix" in r.get_data(as_text=True)
    assert auditats == []


@pytest.mark.parametrize("resp", [
    _Resp(500, b"Error generant el PDF: No se pudo conectar", "text/plain", None),
    _Resp(401, b"Token incorrecte", "text/plain", None),
    _Resp(200, b"<html>proxy</html>", "text/html", None),
])
def test_pdf_error_del_servei_no_s_exposa(client, monkeypatch, resp):
    c, app_module, auditats = client
    _mock_get(monkeypatch, app_module, resp)
    r = c.get("/albarans/148/pdf")
    assert r.status_code == 503
    text = r.get_data(as_text=True)
    assert "Avisa administració" in text
    assert "Token" not in text and "conectar" not in text
    assert auditats == []


def test_pdf_docentry_no_numeric_no_arriba_al_servei(client, monkeypatch):
    c, app_module, _ = client
    crides = _mock_get(monkeypatch, app_module, _Resp())
    assert c.get("/albarans/abc/pdf").status_code == 404
    assert crides == []


# --- Llista -------------------------------------------------------------
def test_api_albarans(client, monkeypatch):
    c, app_module, _ = client
    rebut = []
    monkeypatch.setattr(app_module, "llistar_albarans_carregues",
                        lambda ids: rebut.append(ids) or [{"docentry": 148}])
    r = c.get("/api/albarans?carregues=98, 87")
    assert r.status_code == 200
    assert r.get_json() == {"albarans": [{"docentry": 148}], "pdf": True}
    assert rebut == [[98, 87]]


@pytest.mark.parametrize("qs", ["", "carregues=", "carregues=1,a", "carregues=-1",
                                "carregues=" + ",".join(["1"] * 51)])
def test_api_albarans_valida(client, qs):
    c, _, _ = client
    assert c.get(f"/api/albarans?{qs}").status_code == 400


def test_pantalla_preparacio_nomes_ensenya_albarans_si_hi_ha_servei(client, monkeypatch):
    c, app_module, _ = client
    monkeypatch.setattr(app_module.agrupacions_store, "obtenir", lambda _id: {"nom": "A"})
    assert b'id="mag-albarans"' in c.get("/magatzem/x").data
    monkeypatch.setenv("CRYSTAL_PDF_URL", "")
    assert b'id="mag-albarans"' not in c.get("/magatzem/x").data
