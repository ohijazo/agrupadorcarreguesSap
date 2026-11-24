"""Data d'entrega (U_SEIDataE) de les carregues de SAP i l'excepcio de KAIS:
les d'AGRI i Mª Soledad Lopez el calendari les pinta el dia d'entrega, aixi
que el llistat les ha de tornar si l'entrega cau al rang. Sense SAP: el SQL i
el Service Layer es substitueixen per falsos.
"""
import os
import sys
from datetime import date, datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.environ.get("PREPARACIO_PATH", r"P:\preparacioComandesVendaSAP"))

from dades.sl import carregues as sl  # noqa: E402
from dades.sql import carregues as sql  # noqa: E402

NOMS = {"138": "Mª Soledad López (SACS) 4800MLC", "014": "Agri Energia, SA (Cisterna)",
        "064": "Transportes Escapa, S.A."}


def _capcalera(docentry, transp, sortida, entrega):
    return {"DocEntry": docentry, "DocNum": docentry, "Series": -1, "CreateDate": "2026-11-21T00:00:00Z",
            "U_SEINomCarg": f"C{docentry}", "U_SEIDataS": f"{sortida}T00:00:00Z", "U_SEIHoraS": "20:00:00",
            "U_SEIDataE": f"{entrega}T00:00:00Z" if entrega else None, "U_SEIEstado": "P",
            "U_SEITransp": transp, "U_SEIMatric": "", "U_SEIPesoC": 0, "U_SEIComent": ""}


def test_sql_branca_d_entrega_i_parentesis(monkeypatch):
    vist = {}
    fila = SimpleNamespace(
        DocEntry=7, DocNum=7, Series=-1, CreateDate=datetime(2026, 11, 21), U_SEINomCarg="MATAS",
        U_SEIDataS=datetime(2026, 11, 23), U_SEIHoraS=2000, U_SEIDataE=datetime(2026, 11, 24),
        U_SEIDataT=None, U_SEIHoraT=None, plan_DataS=None, plan_HoraS=None,
        U_SEIEstado="P", tra_codi="138",
        transportista_nom=NOMS["138"], matricula="", U_SEIPesoC=0, observacions="", ruta="",
        palletitzable=False, is_granel=False, kg_total=0, num_comandes=0)

    class Conn:
        def execute(self, s, *params):
            vist.setdefault("sql", s)
            vist.setdefault("params", params)
            return SimpleNamespace(fetchall=lambda: [fila], fetchone=lambda: SimpleNamespace(n=1))

        def close(self):
            pass

    monkeypatch.setattr(sql, "connectar", Conn)
    r = sql.llistar_carregues("2026-11-24", "2026-11-24", tra_codis=["138"], estat=1)
    assert r["items"][0]["car_fecllegada"] == "2026-11-24"
    assert r["items"][0]["car_fecllegada_hora"] is None
    s = " ".join(vist["sql"].split())
    assert "h.U_SEIDataE >= ?" in s and "t.Name LIKE 'AGRI%'" in s
    # El filtre de transportista va despres del parentesi que tanca el OR.
    assert s.index("AND h.U_SEITransp IN") > s.rindex("PEZ%')")
    assert list(vist["params"][:4]) == [date(2026, 11, 24), date(2026, 11, 25)] * 2


def test_sl_afegeix_les_de_soledad_i_agri_per_data_d_entrega(monkeypatch):
    finestra = [_capcalera(3, "064", "2026-11-24", "2026-11-24")]
    per_entrega = [_capcalera(7, "138", "2026-11-23", "2026-11-24"),
                   _capcalera(3, "064", "2026-11-24", "2026-11-24")]  # repetida: no es duplica
    crides = []

    class Client:
        def tot(self, entitat, select=None, filtre="", ordre=None):
            crides.append(filtre)
            return [dict(h) for h in (per_entrega if "U_SEIDataE" in filtre else finestra)]

    monkeypatch.setattr(sl, "client", Client)
    monkeypatch.setattr(sl, "_noms_transportistes", lambda: NOMS)
    monkeypatch.setattr(sl.agregats, "per_carrega", lambda ids: {})
    r = sl.llistar_carregues("2026-11-24", "2026-11-24")

    per_id = {it["car_numero"]: it for it in r["items"]}
    assert set(per_id) == {"3", "7"} and r["total"] == 2
    assert per_id["7"]["car_fecllegada"] == "2026-11-24"
    assert per_id["7"]["car_fecsalida"] == "2026-11-23"
    # La segona crida nomes demana els transportistes de l'excepcio.
    assert "'138'" in crides[1] and "'014'" in crides[1] and "'064'" not in crides[1]


def test_nom_dels_transportistes_de_l_excepcio():
    assert sl._TRANSP_PER_ENTREGA.match("Mª Soledad López (SACS) 1315MST")
    assert sl._TRANSP_PER_ENTREGA.match("Agri Energia, SA (Volvo plataforma)")
    assert not sl._TRANSP_PER_ENTREGA.match("TISA Logistics, SL.")


def test_sql_carrega_sortida_es_queda_al_dia_planificat(monkeypatch):
    """Ordre 3 de produccio: planificada el 23/11 8:00, tancada el 24/11 11:51.
    SAP sobreescriu U_SEIDataS en tancar; el calendari la deixa al 23/11 (la
    de l'historic) i la sortida real va a part."""
    vist = {}
    fila = SimpleNamespace(
        DocEntry=3, DocNum=3, Series=-1, CreateDate=datetime(2026, 11, 21), U_SEINomCarg="JK ASIAN",
        U_SEIDataS=datetime(2026, 11, 24), U_SEIHoraS=1151, U_SEIDataE=datetime(2026, 11, 23),
        U_SEIDataT=None, U_SEIHoraT=None, plan_DataS=datetime(2026, 11, 23), plan_HoraS=800,
        U_SEIEstado="S", tra_codi="064", transportista_nom=NOMS["064"], matricula="", U_SEIPesoC=0,
        observacions="", ruta="", palletitzable=True, is_granel=False, kg_total=0, num_comandes=0)

    class Conn:
        def execute(self, s, *params):
            vist.setdefault("sql", s)
            return SimpleNamespace(fetchall=lambda: [fila], fetchone=lambda: SimpleNamespace(n=1))

        def close(self):
            pass

    monkeypatch.setattr(sql, "connectar", Conn)
    it = sql.llistar_carregues("2026-11-23", "2026-11-23")["items"][0]
    assert (it["car_fecsalida"], it["car_fecsalida_hora"]) == ("2026-11-23", "08:00")
    assert (it["car_sortida_real"], it["car_sortida_real_hora"]) == ("2026-11-24", "11:51")
    s = " ".join(vist["sql"].split())
    assert "OUTER APPLY" in s and "[@ASEI_ORDENCARGA]" in s
    assert "COALESCE(p.DataS, h.U_SEIDataS, h.CreateDate) >= ?" in s
