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
) -> dict:
    """Llista carregues filtrant per rang de data i criteris addicionals.

    Retorna {"items": [...], "total": N, "limit": L, "offset": O}.
    Signatura i format identics als de la variant KAIS per no trencar l'app.
    """
    desde_d = datetime.strptime(desde, "%Y-%m-%d").date()
    fins_d = datetime.strptime(fins, "%Y-%m-%d").date() + timedelta(days=1)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))

    if isinstance(tra_codis, str):
        tra_codis = [c.strip() for c in tra_codis.split(",") if c.strip()]
    elif tra_codis is None:
        tra_codis = []

    # WHERE base: rang de data sobre U_SEIDataS (fallback a CreateDate).
    # No filtrem per Canceled: SAP B1 ignora aquest flag a la finestra
    # "Ordenes de Carga Abiertas" (mostra fins i tot Canceled='Y' si
    # U_SEIEstado='P'). Si cal restringir a un estat concret, es fa amb
    # el parametre opcional `estat`.
    where_sql = """
        WHERE COALESCE(h.U_SEIDataS, h.CreateDate) >= ?
          AND COALESCE(h.U_SEIDataS, h.CreateDate) <  ?
    """
    where_params: list = [desde_d, fins_d]

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
    exists_palletizable_sql = """
        EXISTS (
            SELECT 1
            FROM   ORDR o2 WITH (NOLOCK)
            JOIN   RDR1 l2 WITH (NOLOCK) ON l2.DocEntry = o2.DocEntry
            JOIN   OITM i2 WITH (NOLOCK) ON i2.ItemCode = l2.ItemCode
            WHERE  o2.U_SEIOrdCargId = h.DocEntry
              AND  COALESCE(NULLIF(l2.PackQty, 0), l2.Quantity) > 0
              AND  RTRIM(i2.SalUnitMsr) NOT IN ('UNI', 'GRA')
        )
    """
    exists_granel_sql = """
        EXISTS (
            SELECT 1
            FROM   ORDR o3 WITH (NOLOCK)
            JOIN   RDR1 l3 WITH (NOLOCK) ON l3.DocEntry = o3.DocEntry
            JOIN   OITM i3 WITH (NOLOCK) ON i3.ItemCode = l3.ItemCode
            WHERE  o3.U_SEIOrdCargId = h.DocEntry
              AND  RTRIM(i3.SalUnitMsr) = 'GRA'
              AND  l3.Quantity > 0
        )
    """
    kg_total_sql = """
        ISNULL((
            SELECT SUM(l4.Quantity)
            FROM   ORDR o4 WITH (NOLOCK)
            JOIN   RDR1 l4 WITH (NOLOCK) ON l4.DocEntry = o4.DocEntry
            WHERE  o4.U_SEIOrdCargId = h.DocEntry
        ), 0)
    """
    num_comandes_sql = """
        ISNULL((
            SELECT COUNT(DISTINCT o5.DocEntry)
            FROM   ORDR o5 WITH (NOLOCK)
            WHERE  o5.U_SEIOrdCargId = h.DocEntry
        ), 0)
    """

    sql_items = f"""
        SELECT h.DocEntry, h.DocNum, h.Series, h.CreateDate,
               h.U_SEINomCarg, h.U_SEIDataS, h.U_SEIHoraS,
               h.U_SEIDataE, h.U_SEIDataT, h.U_SEIHoraT,
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
        {where_sql}
        ORDER  BY COALESCE(h.U_SEIDataS, h.CreateDate) DESC, h.DocNum DESC
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """
    sql_count = f"""
        SELECT COUNT(*) AS n
        FROM   [@SEI_ORDENCARGA] h WITH (NOLOCK)
        LEFT   JOIN [@SEITRANSPORTEF] t WITH (NOLOCK)
               ON t.Code = h.U_SEITransp
        {where_sql}
    """

    conn = connectar()
    try:
        total = conn.execute(sql_count, *where_params).fetchone().n
        rows = conn.execute(sql_items, *where_params, offset, limit).fetchall()
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
            "car_fecsalida": r.U_SEIDataS.strftime("%Y-%m-%d") if r.U_SEIDataS else None,
            "car_fecsalida_hora": _fmt_hora(r.U_SEIHoraS),
            # SAP no te data d'arribada: retornem None per compatibilitat.
            "car_fecllegada": None,
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

        if not com_rows:
            return {"comandes": [], "total_sacs": 0, "total_kg": 0.0}

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
                   RTRIM(i.SalUnitMsr) AS tunitat
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

    return {"comandes": out_com, "total_sacs": total_sacs, "total_kg": round(total_kg, 2)}
