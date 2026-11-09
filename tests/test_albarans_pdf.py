"""Tests de la impressio d'albarans: `/api/albarans` i el proxy
`/albarans/<docentry>/pdf` cap al servei `serveis/crystal-pdf`, sense SAP, sense
PostgreSQL i sense el servei (es mockeja `requests.get`).

La paritat SQL/SL de `llistar_albarans_dates` es comprova amb
`scripts/paritat_backends.py --funcio llistar_albarans_dates`.
"""
import os
import sys
import types
from datetime import date

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


# --- Llista ---------------------------------------------------------------
def test_api_albarans(client, monkeypatch):
    c, app_module, _ = client
    rebut = []
    monkeypatch.setenv("ALBARANS_SGA_USUARIS", "23, 22")
    monkeypatch.setattr(app_module, "llistar_albarans_dates",
                        lambda d, f, u: rebut.append((d, f, u)) or [{"docentry": 148}])
    r = c.get("/api/albarans?desde=2026-11-01&fins=2026-11-09")
    assert r.status_code == 200
    assert r.get_json() == {"albarans": [{"docentry": 148, "cancelable": False}],
                            "pdf": True, "cancelar": False}
    assert rebut == [(date(2026, 11, 1), date(2026, 11, 9), [22, 23])]


@pytest.mark.parametrize("qs", ["", "desde=2026-11-01", "fins=2026-11-01",
                                "desde=2026-11-09&fins=2026-11-01",
                                "desde=2026-13-01&fins=2026-13-02",
                                "desde=2026-10-01&fins=2026-11-09",
                                "carregues=98"])
def test_api_albarans_valida(client, monkeypatch, qs):
    c, app_module, _ = client
    monkeypatch.setattr(app_module, "llistar_albarans_dates",
                        lambda *a: pytest.fail("no s'havia de consultar SAP"))
    assert c.get(f"/api/albarans?{qs}").status_code == 400


def test_api_albarans_31_dies_es_el_maxim(client, monkeypatch):
    c, app_module, _ = client
    monkeypatch.setattr(app_module, "llistar_albarans_dates", lambda *a: [])
    # Tots dos dies inclosos: de l'1 al 31 d'octubre son 31 dies.
    assert c.get("/api/albarans?desde=2026-10-01&fins=2026-10-31").status_code == 200
    assert c.get("/api/albarans?desde=2026-10-01&fins=2026-11-01").status_code == 400


def test_preparacio_ja_no_ensenya_albarans(client, monkeypatch):
    c, app_module, _ = client
    monkeypatch.setattr(app_module.agrupacions_store, "obtenir", lambda _id: {"nom": "A"})
    html = c.get("/magatzem/x").data
    assert b"mag-albarans" not in html and b"Albarans de SAP" not in html


def test_pantalla_gestio_albarans(client):
    c, _, _ = client
    r = c.get("/albarans")
    assert r.status_code == 200
    assert b"js/albarans.js" in r.data and b"js/dialogs.js" in r.data


# --- Rols -----------------------------------------------------------------
@pytest.fixture
def amb_rol(client, monkeypatch):
    c, app_module, _ = client
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setattr(app_module, "llistar_albarans_dates", lambda *a: [])
    _mock_get(monkeypatch, app_module, _Resp())

    def entra(rol):
        with c.session_transaction() as sess:
            sess.update(user_id=1, user_name="Prova", user_username="prova@pytest.local", user_rol=rol)
        return c
    return entra


@pytest.mark.parametrize("url", ["/albarans", "/api/albarans?desde=2026-11-09&fins=2026-11-09",
                                 "/albarans/148/pdf"])
def test_magatzem_no_hi_te_acces(amb_rol, url):
    assert amb_rol("magatzem").get(url).status_code == 403


@pytest.mark.parametrize("rol", ["admin", "oficina"])
def test_oficina_i_admin_hi_tenen_acces(amb_rol, rol):
    c = amb_rol(rol)
    r = c.get("/albarans")
    assert r.status_code == 200
    assert b'href="/albarans"' in r.data  # entrada del menu
    assert c.get("/api/albarans?desde=2026-11-09&fins=2026-11-09").status_code == 200
    assert c.get("/albarans/148/pdf").status_code == 200


def test_menu_magatzem_sense_gestio_albarans(amb_rol):
    html = amb_rol("magatzem").get("/magatzem/pendents").data
    assert b"Pendents del dia" in html
    assert b'href="/albarans"' not in html


def test_menu_amaga_gestio_albarans_sense_cap_funcio(amb_rol, monkeypatch):
    monkeypatch.setenv("CRYSTAL_PDF_URL", "")
    monkeypatch.setenv("CANCELAR_ALBARANS", "")
    html = amb_rol("oficina").get("/control").data
    assert b'href="/albarans"' not in html
