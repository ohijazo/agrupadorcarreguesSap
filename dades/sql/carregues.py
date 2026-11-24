"""Consultes de carregues contra SAP B1 (DB_FARIN_TEST).

Mapeig de model KAIS legacy a SAP:
    Cargas          -> @SEI_ORDENCARGA (UDT)
    Detcargas       -> ORDR.U_SEIOrdCargId  (relacio INVERSA: cada comanda
                       diu a quina carrega pertany)
    TRANS           -> @SEITRANSPORTEF
    ARTICLES        -> OITM
    ALBLINIA        -> RDR1 (linies de venda) — l'app agrupa a partir de
                       Sales Orders (ORDR) perque el motor d'embalatges
                       de preparacioComandesVendaSAP treballa amb ORDR.

El `carrega_id` sintetic es
    f"SAP/{Series}/{DocEntry}"
per preservar el format de 3 parts que l'app original espera (eje/sca/car).
Al backend eje="SAP" fa de sentinel, sca=Series, car=DocEntry.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

import pyodbc

# --- Carrega .env local ---
_ARREL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_env_path = os.path.join(_ARREL, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SERVER = os.environ.get("SAP_SQL_SERVER") or os.environ.get("SQL_SERVER", "")
DATABASE = os.environ.get("SAP_SQL_DATABASE") or os.environ.get("SQL_DATABASE", "")
USER = os.environ.get("SAP_SQL_USER") or os.environ.get("SQL_USER", "")
PASSWORD = os.environ.get("SAP_SQL_PASSWORD") or os.environ.get("SQL_PASSWORD", "")

_CONN_STR = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={SERVER};DATABASE={DATABASE};UID={USER};PWD={PASSWORD};"
    f"TrustServerCertificate=yes;APP=AgrupacioCarreguesSAP;"
    f"ApplicationIntent=ReadOnly;"
)


# Transportistes que el calendari pinta el dia d'entrega i no el de sortida
# (excepcio heretada de KAIS, vegeu static/js/calendari.js `usaDataArribada`).
# El backend SL fa el mateix en Python amb `dades.sl.carregues._TRANSP_PER_ENTREGA`.
# Sortida planificada d'una carrega ja sortida ('S'): la de l'ultima versio
# en estat 'P' a l'historic. Per a les que encara son 'P', p.* es NULL i val
# la de la capcalera.
_APPLY_PLANIFICADA = """
        OUTER APPLY (
            SELECT TOP 1 a.U_SEIDataS AS DataS, a.U_SEIHoraS AS HoraS
            FROM   [@ASEI_ORDENCARGA] a WITH (NOLOCK)
            WHERE  a.DocEntry = h.DocEntry
              AND  UPPER(RTRIM(h.U_SEIEstado)) = 'S'
              AND  UPPER(RTRIM(a.U_SEIEstado)) = 'P'
              AND  a.U_SEIDataS IS NOT NULL
            ORDER  BY a.LogInst DESC
        ) p
"""
_DATA_SORTIDA = "COALESCE(p.DataS, h.U_SEIDataS, h.CreateDate)"

_SQL_TRANSP_PER_ENTREGA = "t.Name LIKE 'AGRI%' OR t.Name LIKE 'M% SOLEDAD L%PEZ%'"


def connectar():
    """Obre una connexio SQL a SAP B1. Read-only + timeout 15s."""
    conn = pyodbc.connect(_CONN_STR, timeout=10, autocommit=True)
    conn.timeout = 15
    conn.execute("SET NOCOUNT ON")
    return conn


# =============================================================================
# Helpers de format
# =============================================================================
def _carrega_id(series, docentry) -> str:
    return f"SAP/{series}/{docentry}"


def _fmt_hora(smallint_hhmm) -> str | None:
    """SAP guarda hora com smallint HHMM (ex: 1330 = 13:30, 0 = 00:00)."""
    if smallint_hhmm is None:
        return None
    try:
        h = int(smallint_hhmm)
    except (TypeError, ValueError):
        return None
    if h < 0:
        return None
    hh = h // 100
    mm = h % 100
    return f"{hh:02d}:{mm:02d}"


def _estat_char_to_int(estat_char: str | None) -> int | None:
    """Mapeig U_SEIEstado (1 char) a integer per compatibilitat amb el frontend
    que espera un enter.

    Valors reals observats a DB_FARIN_TEST (2026-08-03):
        'P' -> 1 (Planificada/Pendent — te U_SEIDataS informada)
        'S' -> 2 (Sortida/Servida — te U_SEIDataT informada)

    'C' i 'X' es mantenen mapejats per si SEIDOR els activa en el futur
    (per exemple "Cancel·lada" o "Complete"), pero avui no existeixen a SAP.
    """
    if not estat_char or not estat_char.strip():
        return None
    m = {"P": 1, "S": 2, "C": 3, "X": 4}
    return m.get(estat_char.strip().upper(), 0)


def _estat_int_to_char(estat_int: int | None) -> str | None:
    if estat_int is None:
        return None
    m = {1: "P", 2: "S", 3: "C", 4: "X"}
    return m.get(int(estat_int))


# =============================================================================
# 1) Llistar carregues (query principal)
# =============================================================================
def llistar_carregues(
    desde: str,
    fins: str,
    tra_codis: list[str] | str | None = None,
    estat: int | None = None,
    art_codi: str | None = None,
    limit: int = 500,
    offset: int = 0,
    derivats: bool = True,
) -> dict:
    """Llista carregues filtrant per rang de data i criteris addicionals.

    Retorna {"items": [...], "total": N, "limit": L, "offset": O}.
    Signatura i format identics als de la variant KAIS per no trencar l'app.

    `derivats=False` es salta les 4 subconsultes per carrega (palletitzable,
    is_granel, kg_total, num_comandes, que surten a False/0) i el COUNT
    (`total` = files retornades): per a qui nomes vol les capcaleres, com
    "Preparacio de comanda", que es refresca cada pocs segons.
    """
    desde_d = datetime.strptime(desde, "%Y-%m-%d").date()
    fins_d = datetime.strptime(fins, "%Y-%m-%d").date() + timedelta(days=1)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))

    if isinstance(tra_codis, str):
        tra_codis = [c.strip() for c in tra_codis.split(",") if c.strip()]
    elif tra_codis is None:
        tra_codis = []

    # WHERE base: rang de data sobre la sortida PLANIFICADA (fallback a
    # CreateDate). En tancar una carrega (P -> S), SAP sobreescriu U_SEIDataS i
    # U_SEIHoraS amb la sortida real (U_SEIDataT queda buit): la 3, planificada
    # pel 23/11 a les 8:00, va quedar al 24/11 11:51 i el calendari la movia
    # de dia. La planificada es l'ultima versio en estat 'P' de l'historic de
    # l'objecte (@ASEI_ORDENCARGA): vegeu `_APPLY_PLANIFICADA`.
    # No filtrem per Canceled: SAP B1 ignora aquest flag a la finestra
    # "Ordenes de Carga Abiertas" (mostra fins i tot Canceled='Y' si
    # U_SEIEstado='P'). Si cal restringir a un estat concret, es fa amb
    # el parametre opcional `estat`.
    # Excepcio AGRI / Mª Soledad Lopez (com a KAIS): el calendari les pinta el
    # dia d'entrega (U_SEIDataE), aixi que tambe han de sortir si aquesta data
    # cau al rang encara que la de sortida en quedi fora. Els parentesis externs
    # fan que els AND d'aqui sota s'apliquin a les dues branques del OR.
    where_sql = f"""
        WHERE (
                (
                        {_DATA_SORTIDA} >= ?
                    AND {_DATA_SORTIDA} <  ?
                )
             OR (
                        h.U_SEIDataE >= ?
                    AND h.U_SEIDataE <  ?
                    AND ({_SQL_TRANSP_PER_ENTREGA})
                )
        )
    """
    where_params: list = [desde_d, fins_d, desde_d, fins_d]

    if tra_codis:
        placeholders = ",".join(["?"] * len(tra_codis))
        where_sql += f" AND h.U_SEITransp IN ({placeholders})"
        where_params.extend(tra_codis)

    if estat is not None:
        estat_c = _estat_int_to_char(int(estat))
        if estat_c:
            where_sql += " AND UPPER(RTRIM(h.U_SEIEstado)) = ?"
            where_params.append(estat_c)

    if art_codi:
        # Existeix alguna ORDR d'aquesta carrega amb una linia d'aquest article.
        where_sql += """
          AND EXISTS (
              SELECT 1
              FROM   ORDR o WITH (NOLOCK)
              JOIN   RDR1 l WITH (NOLOCK) ON l.DocEntry = o.DocEntry
              WHERE  o.U_SEIOrdCargId = h.DocEntry
                AND  RTRIM(l.ItemCode) = ?
          )
        """
        where_params.append(art_codi)

    # SUB-consultes derivades (num_comandes, palletitzable, is_granel, kg_total).
    # Una carrega porta comandes de venda (ORDR) i sol·licituds de trasllat a
    # un altre magatzem (OWTQ, p. ex. 01 -> 05 Mallorca), totes dues lligades
    # per `U_SEIOrdCargId`. Les dues compten: una carrega nomes de trasllats
    # sortia al calendari amb 0 comandes i 0 kg (23/11, carregues 29 i 38).
    # Granel = unitat GRA/KG/KGS, o propietat 5 ("Es Granel") si la unitat no
    # es de sacs: a produccio el granel te SalUnitMsr 'KGS', no 'GRA'. Mateix
    # criteri que preparacioComandesVendaSAP/unitats_sap.py (el motor).
    exists_palletizable_sql = """
        EXISTS (
            SELECT 1
            FROM   ORDR o2 WITH (NOLOCK)
            JOIN   RDR1 l2 WITH (NOLOCK) ON l2.DocEntry = o2.DocEntry
            JOIN   OITM i2 WITH (NOLOCK) ON i2.ItemCode = l2.ItemCode
            WHERE  o2.U_SEIOrdCargId = h.DocEntry
              AND  COALESCE(NULLIF(l2.PackQty, 0), l2.Quantity) > 0
              AND  RTRIM(i2.SalUnitMsr) <> 'UNI'
              AND  NOT (UPPER(RTRIM(ISNULL(i2.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (i2.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(i2.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
        )
        OR EXISTS (
            SELECT 1
            FROM   OWTQ q2 WITH (NOLOCK)
            JOIN   WTQ1 m2 WITH (NOLOCK) ON m2.DocEntry = q2.DocEntry
            JOIN   OITM j2 WITH (NOLOCK) ON j2.ItemCode = m2.ItemCode
            WHERE  q2.U_SEIOrdCargId = h.DocEntry
              AND  m2.Quantity > 0
              AND  RTRIM(j2.SalUnitMsr) <> 'UNI'
              AND  NOT (UPPER(RTRIM(ISNULL(j2.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (j2.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(j2.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
        )
    """
    exists_granel_sql = """
        EXISTS (
            SELECT 1
            FROM   ORDR o3 WITH (NOLOCK)
            JOIN   RDR1 l3 WITH (NOLOCK) ON l3.DocEntry = o3.DocEntry
            JOIN   OITM i3 WITH (NOLOCK) ON i3.ItemCode = l3.ItemCode
            WHERE  o3.U_SEIOrdCargId = h.DocEntry
              AND  (UPPER(RTRIM(ISNULL(i3.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (i3.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(i3.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
              AND  l3.Quantity > 0
        )
        OR EXISTS (
            SELECT 1
            FROM   OWTQ q3 WITH (NOLOCK)
            JOIN   WTQ1 m3 WITH (NOLOCK) ON m3.DocEntry = q3.DocEntry
            JOIN   OITM j3 WITH (NOLOCK) ON j3.ItemCode = m3.ItemCode
            WHERE  q3.U_SEIOrdCargId = h.DocEntry
              AND  (UPPER(RTRIM(ISNULL(j3.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (j3.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(j3.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
              AND  m3.Quantity > 0
        )
    """
    kg_total_sql = """
        ISNULL((
            SELECT SUM(l4.Quantity)
            FROM   ORDR o4 WITH (NOLOCK)
            JOIN   RDR1 l4 WITH (NOLOCK) ON l4.DocEntry = o4.DocEntry
            WHERE  o4.U_SEIOrdCargId = h.DocEntry
        ), 0) + ISNULL((
            SELECT SUM(m4.Quantity)
            FROM   OWTQ q4 WITH (NOLOCK)
            JOIN   WTQ1 m4 WITH (NOLOCK) ON m4.DocEntry = q4.DocEntry
            WHERE  q4.U_SEIOrdCargId = h.DocEntry
        ), 0)
    """
    num_comandes_sql = """
        ISNULL((
            SELECT COUNT(DISTINCT o5.DocEntry)
            FROM   ORDR o5 WITH (NOLOCK)
            WHERE  o5.U_SEIOrdCargId = h.DocEntry
        ), 0) + ISNULL((
            SELECT COUNT(*)
            FROM   OWTQ q5 WITH (NOLOCK)
            WHERE  q5.U_SEIOrdCargId = h.DocEntry
        ), 0)
    """

    if not derivats:
        exists_palletizable_sql = exists_granel_sql = "1 = 0"
        kg_total_sql = num_comandes_sql = "0"

    sql_items = f"""
        SELECT h.DocEntry, h.DocNum, h.Series, h.CreateDate,
               h.U_SEINomCarg, h.U_SEIDataS, h.U_SEIHoraS,
               h.U_SEIDataE, h.U_SEIDataT, h.U_SEIHoraT,
               p.DataS AS plan_DataS, p.HoraS AS plan_HoraS,
               h.U_SEIEstado, RTRIM(h.U_SEITransp) AS tra_codi,
               RTRIM(t.Name) AS transportista_nom,
               RTRIM(h.U_SEIMatric) AS matricula,
               h.U_SEIPesoC,
               CAST(h.U_SEIComent AS varchar(500)) AS observacions,
               RTRIM(h.U_SEIRuta) AS ruta,
               CAST(CASE WHEN {exists_palletizable_sql} THEN 1 ELSE 0 END AS BIT) AS palletitzable,
               CAST(CASE WHEN {exists_granel_sql} THEN 1 ELSE 0 END AS BIT) AS is_granel,
               {kg_total_sql} AS kg_total,
               {num_comandes_sql} AS num_comandes
        FROM   [@SEI_ORDENCARGA] h WITH (NOLOCK)
        LEFT   JOIN [@SEITRANSPORTEF] t WITH (NOLOCK)
               ON t.Code = h.U_SEITransp
        {_APPLY_PLANIFICADA}
        {where_sql}
        ORDER  BY {_DATA_SORTIDA} DESC, h.DocNum DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    sql_count = f"""
        SELECT COUNT(*) AS n
        FROM   [@SEI_ORDENCARGA] h WITH (NOLOCK)
        LEFT   JOIN [@SEITRANSPORTEF] t WITH (NOLOCK)
               ON t.Code = h.U_SEITransp
        {_APPLY_PLANIFICADA}
        {where_sql}
    """

    conn = connectar()
    try:
        rows = conn.execute(sql_items, *where_params, offset, limit).fetchall()
        total = (conn.execute(sql_count, *where_params).fetchone().n if derivats
                 else offset + len(rows))
    finally:
        conn.close()

    items = []
    for r in rows:
        series = r.Series if r.Series is not None else 0
        docentry = r.DocEntry
        eje = "SAP"
        sca = str(series)
        car = str(docentry)
        items.append({
            "eje_ejercicio": eje,
            "sca_serie": sca,
            "car_numero": car,
            "carrega_id": _carrega_id(series, docentry),
            "car_descripcion": (r.U_SEINomCarg or "").strip() if r.U_SEINomCarg else "",
            "car_fecha": r.CreateDate.strftime("%Y-%m-%d") if r.CreateDate else None,
            # Sortida planificada; si la carrega ja ha sortit, la real va a part.
            "car_fecsalida": (r.plan_DataS or r.U_SEIDataS).strftime("%Y-%m-%d")
                             if (r.plan_DataS or r.U_SEIDataS) else None,
            "car_fecsalida_hora": _fmt_hora(r.plan_HoraS if r.plan_DataS else r.U_SEIHoraS),
            "car_sortida_real": (r.U_SEIDataS.strftime("%Y-%m-%d")
                                 if r.plan_DataS and r.U_SEIDataS else None),
            "car_sortida_real_hora": _fmt_hora(r.U_SEIHoraS) if r.plan_DataS else None,
            # "Fecha de entrega prevista". SAP no en guarda l'hora.
            "car_fecllegada": r.U_SEIDataE.strftime("%Y-%m-%d") if r.U_SEIDataE else None,
            "car_fecllegada_hora": None,
            "car_estat": _estat_char_to_int(r.U_SEIEstado) or 0,
            "tra_codi": r.tra_codi or "",
            "transportista": (r.transportista_nom or "").strip(),
            "car_matricula": r.matricula or "",
            # SAP no te camp conductor; retornem cadena buida.
            "car_nomconductor": "",
            "car_pesonetocarga": float(r.U_SEIPesoC) if r.U_SEIPesoC is not None else 0.0,
            "car_pesoteorico": 0.0,
            "car_observaciones": (r.observacions or "").strip(),
            "palletitzable": bool(r.palletitzable),
            "is_granel": bool(r.is_granel),
            "kg_total": float(r.kg_total) if r.kg_total is not None else 0.0,
            "num_comandes": int(r.num_comandes) if r.num_comandes is not None else 0,
        })
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


# =============================================================================
# 2) Estats de carrega (dropdown filtre)
# =============================================================================
def llistar_estats_carregues() -> list[dict]:
    """Estats distints amb el comptador de l'ultim any."""
    sql = """
        SELECT UPPER(RTRIM(U_SEIEstado)) AS estat_char, COUNT(*) AS n
        FROM   [@SEI_ORDENCARGA] WITH (NOLOCK)
        WHERE  COALESCE(U_SEIDataS, CreateDate) >= DATEADD(YEAR, -1, GETDATE())
        GROUP  BY UPPER(RTRIM(U_SEIEstado))
        ORDER  BY estat_char
    """
    conn = connectar()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        estat_int = _estat_char_to_int(r.estat_char)
        if estat_int is None:
            continue
        out.append({"estat": estat_int, "n": int(r.n)})
    return out


# =============================================================================
# 3) Transportistes (dropdown filtre)
# =============================================================================
def llistar_transportistes() -> list[dict]:
    """Llistat de transportistes efectius amb almenys una carrega l'ultim any."""
    sql = """
        SELECT DISTINCT RTRIM(t.Code) AS tra_codi, RTRIM(t.Name) AS tra_nom
        FROM   [@SEITRANSPORTEF] t WITH (NOLOCK)
        JOIN   [@SEI_ORDENCARGA] h WITH (NOLOCK) ON h.U_SEITransp = t.Code
        WHERE  COALESCE(h.U_SEIDataS, h.CreateDate) >= DATEADD(YEAR, -1, GETDATE())
        ORDER  BY tra_nom
    """
    conn = connectar()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [{"tra_codi": r.tra_codi, "tra_nom": r.tra_nom or ""} for r in rows]


# =============================================================================
# 4) Cercar articles (autocomplete filtre article)
# =============================================================================
def cercar_articles(q: str, limit: int = 20) -> list[dict]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    limit = max(1, min(int(limit), 50))
    pat = f"%{q}%"
    sql = """
        SELECT TOP (?) RTRIM(ItemCode) AS art_codi, RTRIM(ItemName) AS art_descrip
        FROM   OITM WITH (NOLOCK)
        WHERE  ItemCode LIKE ? OR ItemName LIKE ?
        ORDER  BY CASE WHEN ItemCode LIKE ? THEN 0 ELSE 1 END, ItemCode
    """
    conn = connectar()
    try:
        rows = conn.execute(sql, limit, pat, pat, pat).fetchall()
    finally:
        conn.close()
    return [{"art_codi": r.art_codi, "art_descrip": (r.art_descrip or "").strip()} for r in rows]


# =============================================================================
# 5) Descripcio articles (batch lookup)
# =============================================================================
def obtenir_descrip_articles(codis: list[str]) -> dict[str, str]:
    codis = [c for c in (codis or []) if c]
    if not codis:
        return {}
    seen = set()
    unics = []
    for c in codis:
        if c not in seen:
            seen.add(c)
            unics.append(c)
    placeholders = ",".join(["?"] * len(unics))
    sql = f"""
        SELECT RTRIM(ItemCode) AS art_codi, RTRIM(ItemName) AS art_descrip
        FROM   OITM WITH (NOLOCK)
        WHERE  ItemCode IN ({placeholders})
    """
    conn = connectar()
    try:
        rows = conn.execute(sql, *unics).fetchall()
    finally:
        conn.close()
    return {r.art_codi: (r.art_descrip or "").strip() for r in rows}


# =============================================================================
# 6) Comandes d'una carrega (per agregador)
# =============================================================================
def obtenir_comandes_carrega(eje: str, sca: str, car: str) -> list[dict]:
    """Comandes SAP (ORDR) que pertanyen a una carrega.

    `eje` es sempre "SAP" (sentinel); `sca` es la Series; `car` es el
    DocEntry de la carrega. Ignorem eje/sca i usem car (DocEntry).

    Format de retorn compatible amb l'agregador:
        {eje_ejercicio, sal_codigo, cpa_albara, det_tipo}
    on:
        sal_codigo = str(ORDR.Series)
        cpa_albara = str(ORDR.DocNum)
        det_tipo   = 'A' (sentinel — no aplicable a SAP)

    El motor SAP `calcular_embalatges(sal_codigo, cpa_albara)` de
    preparacioComandesVendaSAP interpreta els params com Series/DocNum de ORDR.
    """
    try:
        docentry_carrega = int(car)
    except (TypeError, ValueError):
        return []

    sql = """
        SELECT o.DocEntry, o.DocNum, o.Series, o.CardCode, o.DocDate
        FROM   ORDR o WITH (NOLOCK)
        WHERE  o.U_SEIOrdCargId = ?
        ORDER  BY o.Series, o.DocNum
    """
    conn = connectar()
    try:
        rows = conn.execute(sql, docentry_carrega).fetchall()
    finally:
        conn.close()
    return [
        {
            "eje_ejercicio": eje or "SAP",
            "sal_codigo": str(r.Series if r.Series is not None else 0),
            "cpa_albara": str(r.DocNum),
            "det_tipo": "A",
        }
        for r in rows
    ]


# =============================================================================
# 7) Previsualitzacio de carrega (comandes + linies + kg)
# =============================================================================
def _tunitat_es_palletizable(tun: str, unitats: float) -> bool:
    tun = (tun or "").strip().upper()
    return tun not in ("UNI", "GRA") and unitats > 0


def resum_carrega(eje: str, sca: str, car: str) -> dict:
    """Previsualitzacio del contingut d'una carrega — comandes agrupades
    per DocEntry amb linies. Format identic al de KAIS.
    """
    try:
        docentry_carrega = int(car)
    except (TypeError, ValueError):
        return {"comandes": [], "total_sacs": 0, "total_kg": 0.0}

    conn = connectar()
    try:
        sql_com = """
            SELECT o.DocEntry, o.DocNum, o.Series, RTRIM(o.CardCode) AS cli_codi,
                   RTRIM(bp.CardName) AS cli_nom,
                   RTRIM(o.ShipToCode) AS adr_codi,
                   RTRIM(bp.City) AS cli_ciutat
            FROM   ORDR o WITH (NOLOCK)
            LEFT   JOIN OCRD bp WITH (NOLOCK) ON bp.CardCode = o.CardCode
            WHERE  o.U_SEIOrdCargId = ?
            ORDER  BY o.Series, o.DocNum
        """
        com_rows = conn.execute(sql_com, docentry_carrega).fetchall()
        trasllats = _trasllats_carrega(conn, docentry_carrega)

        if not com_rows:
            return _amb_trasllats({"comandes": [], "total_sacs": 0, "total_kg": 0.0},
                                  trasllats)

        docentries = [r.DocEntry for r in com_rows]
        placeholders = ",".join(["?"] * len(docentries))

        # Ciutat concreta de l'adreca d'enviament (CRD1). Fallback a bp.City.
        adreces_map: dict[tuple[str, str], str] = {}
        adr_pairs = [(r.cli_codi, r.adr_codi) for r in com_rows if r.cli_codi and r.adr_codi]
        if adr_pairs:
            addr_ph = ",".join(["(?, ?)"] * len(adr_pairs))
            addr_flat: list = []
            for cli, adr in adr_pairs:
                addr_flat.extend([cli, adr])
            sql_adr = f"""
                SELECT RTRIM(a.CardCode) AS cli, RTRIM(a.Address) AS adr,
                       RTRIM(a.City) AS ciutat
                FROM   CRD1 a WITH (NOLOCK)
                JOIN   (VALUES {addr_ph}) v(cli, adr)
                       ON v.cli = a.CardCode AND v.adr = a.Address
                WHERE  a.AdresType = 'S'
            """
            for r in conn.execute(sql_adr, *addr_flat).fetchall():
                adreces_map[(r.cli, r.adr)] = (r.ciutat or "").strip()

        # Linies de totes les comandes en una query
        sql_lin = f"""
            SELECT l.DocEntry, l.LineNum,
                   RTRIM(l.ItemCode) AS art_codi,
                   RTRIM(l.Dscription) AS art_descrip,
                   COALESCE(NULLIF(l.PackQty, 0), l.Quantity) AS unitats,
                   l.Quantity AS quan,
                   CASE WHEN (UPPER(RTRIM(ISNULL(i.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (i.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(i.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
                        THEN 'GRA' ELSE
             -- S25KG -> S25 (unitats_sap.sql_unitat_sacs)
             CASE WHEN UPPER(RTRIM(i.SalUnitMsr)) LIKE 'S[0-9]%KG' AND UPPER(LEFT(RTRIM(i.SalUnitMsr), LEN(RTRIM(i.SalUnitMsr)) - 2)) NOT LIKE 'S%[^0-9]%' THEN LEFT(RTRIM(i.SalUnitMsr), LEN(RTRIM(i.SalUnitMsr)) - 2) ELSE RTRIM(i.SalUnitMsr) END END AS tunitat
            FROM   RDR1 l WITH (NOLOCK)
            LEFT   JOIN OITM i WITH (NOLOCK) ON i.ItemCode = l.ItemCode
            WHERE  l.DocEntry IN ({placeholders})
            ORDER  BY l.DocEntry, l.LineNum
        """
        lin_rows = conn.execute(sql_lin, *docentries).fetchall()
    finally:
        conn.close()

    # Agrupar linies per DocEntry
    linies_per_docentry: dict[int, list[dict]] = {}
    for r in lin_rows:
        tun = (r.tunitat or "").strip()
        unitats = float(r.unitats or 0)
        quan = float(r.quan or 0)
        palletizable = _tunitat_es_palletizable(tun, unitats)
        kg = quan if quan > 0 else 0.0
        linies_per_docentry.setdefault(r.DocEntry, []).append({
            "art_codi": r.art_codi,
            "art_descrip": (r.art_descrip or "").strip(),
            "sacs": int(unitats),
            "quan": quan,
            "tunitat": tun,
            "kg": round(kg, 2),
            "palletitzable": palletizable,
        })

    total_sacs = 0
    total_kg = 0.0
    out_com = []
    for r in com_rows:
        linies = linies_per_docentry.get(r.DocEntry, [])
        a_sacs = sum(l["sacs"] for l in linies if l["palletitzable"])
        a_kg = sum(l["kg"] for l in linies)
        total_sacs += a_sacs
        total_kg += a_kg
        pobla = adreces_map.get((r.cli_codi, r.adr_codi), "") or (r.cli_ciutat or "").strip()
        out_com.append({
            "comanda": f"{r.Series if r.Series is not None else 0}/{r.DocNum}",
            "det_tipo": "A",
            "cli_codi": r.cli_codi or "",
            "cli_nom": (r.cli_nom or "").strip(),
            "pobla": pobla,
            "total_sacs": a_sacs,
            "total_kg": round(a_kg, 2),
            "linies": linies,
        })

    out_com.sort(key=lambda c: (1 if not (c.get("pobla") or "") else 0,
                                (c.get("pobla") or "").upper(),
                                (c.get("cli_nom") or "").upper()))

    return _amb_trasllats(
        {"comandes": out_com, "total_sacs": total_sacs, "total_kg": round(total_kg, 2)},
        trasllats)


def _sacs_trasllat(quan: float, unitat_venda: str) -> int:
    """Sacs d'una linia de trasllat.

    A les comandes SAP posa els sacs a `PackQty`, pero a les sol·licituds de
    trasllat el deixa a 0 i nomes hi ha els kg. Es treuen de la unitat de
    venda de l'article: S25KG -> 25 kg per sac. Les altres (UNI, palets) ja
    son unitats.
    """
    m = re.fullmatch(r"S(\d+(?:[.,]\d+)?)KG", (unitat_venda or "").strip().upper())
    if not m:
        return int(quan)
    kg_sac = float(m.group(1).replace(",", "."))
    return int(round(quan / kg_sac)) if kg_sac > 0 else int(quan)


def _trasllats_carrega(conn, docentry_carrega: int) -> list[dict]:
    """Sol·licituds de trasllat (OWTQ) d'una carrega, amb el format de les
    comandes del detall.

    Una carrega pot portar mercaderia cap a un altre magatzem nostre (01 ->
    05 Mallorca, 01 -> 04 Salzadella) en lloc de, o a mes de, comandes de
    venda. El "client" es el magatzem de desti.
    """
    sql = """
        SELECT q.DocEntry, q.DocNum, RTRIM(q.ToWhsCode) AS whs_codi,
               RTRIM(w.WhsName) AS whs_nom, RTRIM(w.City) AS whs_ciutat,
               RTRIM(l.ItemCode) AS art_codi,
               RTRIM(l.Dscription) AS art_descrip,
               l.Quantity AS quan, l.PackQty AS paq,
               RTRIM(i.SalUnitMsr) AS unitat_venda,
               CASE WHEN (UPPER(RTRIM(ISNULL(i.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (i.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(i.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
                    THEN 'GRA' ELSE
             CASE WHEN UPPER(RTRIM(i.SalUnitMsr)) LIKE 'S[0-9]%KG' AND UPPER(LEFT(RTRIM(i.SalUnitMsr), LEN(RTRIM(i.SalUnitMsr)) - 2)) NOT LIKE 'S%[^0-9]%' THEN LEFT(RTRIM(i.SalUnitMsr), LEN(RTRIM(i.SalUnitMsr)) - 2) ELSE RTRIM(i.SalUnitMsr) END END AS tunitat
        FROM   OWTQ q WITH (NOLOCK)
        JOIN   WTQ1 l WITH (NOLOCK) ON l.DocEntry = q.DocEntry
        LEFT   JOIN OITM i WITH (NOLOCK) ON i.ItemCode = l.ItemCode
        LEFT   JOIN OWHS w WITH (NOLOCK) ON w.WhsCode = q.ToWhsCode
        WHERE  q.U_SEIOrdCargId = ?
        ORDER  BY q.DocNum, l.LineNum
    """
    per_doc: dict[int, dict] = {}
    for r in conn.execute(sql, docentry_carrega).fetchall():
        quan = float(r.quan or 0)
        paq = float(r.paq or 0)
        sacs = int(paq) if paq > 0 else _sacs_trasllat(quan, r.unitat_venda)
        tun = (r.tunitat or "").strip()
        palletizable = _tunitat_es_palletizable(tun, sacs)
        doc = per_doc.setdefault(r.DocEntry, {
            "comanda": f"Trasllat {r.DocNum}",
            "det_tipo": "T",
            "cli_codi": r.whs_codi or "",
            "cli_nom": (r.whs_nom or "").strip(),
            "pobla": (r.whs_ciutat or "").strip(),
            "total_sacs": 0,
            "total_kg": 0.0,
            "linies": [],
        })
        kg = quan if quan > 0 else 0.0
        doc["linies"].append({
            "art_codi": r.art_codi,
            "art_descrip": (r.art_descrip or "").strip(),
            "sacs": sacs,
            "quan": quan,
            "tunitat": tun,
            "kg": round(kg, 2),
            "palletitzable": palletizable,
        })
        if palletizable:
            doc["total_sacs"] += sacs
        doc["total_kg"] = round(doc["total_kg"] + kg, 2)
    return list(per_doc.values())


def _amb_trasllats(resum: dict, trasllats: list[dict]) -> dict:
    """Afegeix els trasllats al final del detall i als totals."""
    if not trasllats:
        return resum
    return {
        "comandes": resum["comandes"] + trasllats,
        "total_sacs": resum["total_sacs"] + sum(t["total_sacs"] for t in trasllats),
        "total_kg": round(resum["total_kg"] + sum(t["total_kg"] for t in trasllats), 2),
    }
