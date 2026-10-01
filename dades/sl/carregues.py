"""Consultes de carregues contra SAP B1 pel Service Layer.

Mateix contracte que `dades/sql/carregues.py`: les funcions han de retornar
exactament el mateix, perque la facana les commuta sense que els cridants se
n'adonin. Les diferencies respecte del SQL estan comentades alla on hi son.

Nomes hi ha aqui les funcions ja migrades. La facana usa SQL per a les que
encara no existeixen en aquest modul.

Tres limitacions del Service Layer que condicionen tot el que hi ha aqui
(provades contra la instal·lacio real, B1 10.0 / OData v3):

  - No hi ha cap JOIN: 0 navigation properties en 436 entitats. Tot
    creuament de taules es resol amb mes d'una crida i un merge en Python.
  - No es pot agregar ni filtrar sobre linies de document.
  - `$orderby` no accepta funcions, i no hi ha `toupper` ni `trim`. Tot el que
    depengui d'aixo es fa en Python amb la semantica exacta del SQL.
"""
from __future__ import annotations

import logging
import os
import time
import unicodedata
from datetime import datetime, timedelta

from dades import agregats
from sl_lectura import cache_articles
from sl_lectura import odata as od
from sl_lectura.client import client
from dades.sql.carregues import _carrega_id, _estat_char_to_int, _estat_int_to_char
from dades.sql.carregues import _tunitat_es_palletizable as _es_palletizable
from sap_service_layer import SLError

log = logging.getLogger("agrupacio")

ORDRES = "SEI_ORDENCARGA"        # te UDO: va SENSE prefix U_
TRANSPORTISTES = "U_SEITRANSPORTEF"  # UDT simple: va AMB prefix U_


def _fa_un_any(ara: datetime | None = None) -> datetime:
    """Equivalent de `DATEADD(YEAR, -1, GETDATE())` de SQL Server.

    Dos detalls que importen per a la paritat:

    - Es conserva **l'hora**. El SQL compara contra `GETDATE()`, que porta
      hora; si emetessim la data a mitjanit, el dia frontera entraria al
      Service Layer i no al SQL. Es una fila de diferencia a l'any, i es
      exactament el tipus de discrepancia que fa desconfiar d'un comparador.
    - El 29 de febrer, `DATEADD` cau al 28. Ho repliquem.

    El rellotge, aixo si, passa a ser el del proces Python en lloc del del
    SQL Server. Son la mateixa LAN i van sincronitzats, pero si algun dia
    divergissin es veuria aqui.
    """
    ara = ara or datetime.now()
    try:
        return ara.replace(year=ara.year - 1)
    except ValueError:  # 29 de febrer
        return ara.replace(year=ara.year - 1, day=28)


def _finestra_ultim_any() -> str:
    """`COALESCE(U_SEIDataS, CreateDate) >= fa un any`, sense limit superior."""
    desde = _fa_un_any()
    return od.o(
        od.i("U_SEIDataS ne null", f"U_SEIDataS ge {od.data_hora(desde)}"),
        od.i("U_SEIDataS eq null", f"CreateDate ge {od.data_hora(desde)}"),
    )


# =============================================================================
# Estats de carrega (dropdown de filtre)
# =============================================================================
def llistar_estats_carregues() -> list[dict]:
    """Estats distints amb el comptador de l'ultim any. Una sola crida.

    El SQL agrupa per `UPPER(RTRIM(U_SEIEstado))`; el Service Layer agrupa pel
    valor cru, i per tant 'P', 'p' i 'P ' hi serien tres grups separats on el
    SQL en te un. Reagreguem en Python per garantir el mateix resultat.
    """
    grups = client().agrega(
        ORDRES,
        f"filter({_finestra_ultim_any()})/groupby((U_SEIEstado),aggregate($count as n))",
    )

    per_estat: dict[str, int] = {}
    for g in grups:
        brut = g.get("U_SEIEstado")
        clau = (brut or "").strip().upper()
        per_estat[clau] = per_estat.get(clau, 0) + int(g.get("n") or 0)

    out = []
    for estat_char in sorted(per_estat):
        estat_int = _estat_char_to_int(estat_char)
        if estat_int is None:   # estat buit: el SQL tambe el descarta
            continue
        out.append({"estat": estat_int, "n": per_estat[estat_char]})
    return out


# =============================================================================
# Transportistes (dropdown de filtre)
# =============================================================================
def llistar_transportistes() -> list[dict]:
    """Transportistes efectius amb almenys una carrega l'ultim any. Dues crides.

    Substitueix el `DISTINCT` + `INNER JOIN` entre dues UDT del SQL: una crida
    dona els codis usats (`groupby`), l'altra la taula de transportistes
    sencera (son poques files), i el creuament es fa aqui.

    El JOIN del SQL es INNER: un `U_SEITransp` que no tingui fila a la taula de
    transportistes avui desapareix del desplegable, i ha de continuar
    desapareixent.
    """
    c = client()
    grups = c.agrega(ORDRES, f"filter({_finestra_ultim_any()})/groupby((U_SEITransp))")
    codis_usats = {
        (g.get("U_SEITransp") or "").strip()
        for g in grups
        if (g.get("U_SEITransp") or "").strip()
    }
    if not codis_usats:
        return []

    files = c.tot(TRANSPORTISTES, select="Code,Name")
    out = []
    for f in files:
        codi = (f.get("Code") or "").strip()
        if codi in codis_usats:
            out.append({"tra_codi": codi, "tra_nom": (f.get("Name") or "").strip()})

    out.sort(key=lambda r: _clau_collation(r["tra_nom"]))
    return out


def _clau_collation(valor: str) -> tuple[str, str]:
    """Clau d'ordenacio que imita la collation de la BD.

    La BD es `SQL_Latin1_General_CP850_CI_AS`: insensible a majuscules,
    SENSIBLE a accents. Un `sorted()` per codepoint no hi serveix, i es va
    veure amb un cas real: el transportista "Mª Soledad López" ha
    d'anar abans de "Mascaro Morera" perque la collation tracta la ª com
    una 'a', mentre que el seu codepoint (U+00AA) la posa despres de "Movex".

    Fem el que fa una collation: descomposem (NFKD, que converteix les formes
    de compatibilitat com ª en 'a'), i separem el pes primari (les lletres
    base, en majuscules -> insensible a majuscules) del secundari (les marques
    diacritiques -> sensible a accents, pero nomes com a desempat).
    """
    d = unicodedata.normalize("NFKD", valor or "").upper()
    base = "".join(c for c in d if not unicodedata.combining(c))
    marques = "".join(c for c in d if unicodedata.combining(c))
    return (base, marques)


# =============================================================================
# Articles
# =============================================================================
ARTICLES = "Items"


def cercar_articles(q: str, limit: int = 20) -> list[dict]:
    """Autocomplete d'articles. Una o dues crides.

    El SQL fa, en una sola consulta:

        WHERE ItemCode LIKE '%q%' OR ItemName LIKE '%q%'
        ORDER BY CASE WHEN ItemCode LIKE '%q%' THEN 0 ELSE 1 END, ItemCode

    es a dir, dos grups: primer el que casa pel codi, despres el que nomes
    casa pel nom, cada grup per codi, i tallat a `limit`. Ho reproduim amb dues
    crides, i la segona nomes si la primera no ha omplert el limit.

    La cerca es fa al servidor (`substringof`) i no sobre la cache d'articles a
    proposit: el Service Layer la tradueix a SQL i per tant hereta la collation
    de la BD (`CP850_CI_AS`, insensible a majuscules). Un matching en Python
    seria sensible a majuscules i divergiria.

    Diferencia coneguda i acceptada: a `LIKE`, un `%` o un `_` dins del text
    buscat son comodins; a `substringof` son literals. Nomes es nota si algu
    escriu aquests caracters al cercador.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return []
    limit = max(1, min(int(limit), 50))

    c = client()
    patro = od.text(q)

    per_codi = c.tot(ARTICLES, select="ItemCode,ItemName",
                     filtre=f"substringof({patro},ItemCode)",
                     ordre="ItemCode", top=limit)
    out = [{"art_codi": (f.get("ItemCode") or "").strip(),
            "art_descrip": (f.get("ItemName") or "").strip()}
           for f in per_codi]
    if len(out) >= limit:
        return out[:limit]

    # Nomes els que casen pel nom i NO pel codi (els del primer grup ja hi son,
    # i el primer grup es complet perque no ha arribat al limit).
    ja_hi_son = {r["art_codi"] for r in out}
    per_nom = c.tot(ARTICLES, select="ItemCode,ItemName",
                    filtre=f"substringof({patro},ItemName)",
                    ordre="ItemCode", top=limit)
    for f in per_nom:
        codi = (f.get("ItemCode") or "").strip()
        if codi in ja_hi_son:
            continue
        out.append({"art_codi": codi,
                    "art_descrip": (f.get("ItemName") or "").strip()})
        if len(out) >= limit:
            break
    return out[:limit]


def obtenir_descrip_articles(codis: list[str]) -> dict[str, str]:
    """Descripcions dels articles demanats. Normalment 0 crides (cache)."""
    codis = [c for c in (codis or []) if c]
    if not codis:
        return {}
    unics = list(dict.fromkeys(codis))   # dedup preservant l'ordre, com el SQL
    return {c: d["art_descrip"] for c, d in cache_articles.consulta(unics).items()}


def escalfa() -> None:
    """Prepara el que es car de preparar, per no fer-ho pagar al primer usuari.

    La crida /health ho invoca si alguna funcio llegeix per Service Layer.
    Portar-se el mestre d'articles son ~1,3 s; fer-ho aqui vol dir que la
    primera agrupacio del dia no se'ls menja. Es idempotent: despres de la
    primera vegada la cache el serveix de memoria fins que caduca.
    """
    cache_articles.mapa()


# =============================================================================
# Comandes d'una carrega
# =============================================================================
COMANDES = "Orders"
INTERLOCUTORS = "BusinessPartners"


def obtenir_comandes_carrega(eje: str, sca: str, car: str) -> list[dict]:
    """Comandes que pertanyen a una carrega. Una crida.

    La relacio carrega -> comandes va per un camp d'usuari de la capcalera de
    comanda (`U_SEIOrdCargId`), que SI es filtrable al Service Layer. La taula
    filla de l'UDO (`@ASEI_ORDENCARGA`) no hi esta exposada, pero no ens fa
    falta precisament per aixo.

    No demanem `DocumentLines`: aqui no es fan servir, i afegir-les
    multiplicaria el payload per ~50.
    """
    try:
        docentry_carrega = int(car)
    except (TypeError, ValueError):
        return []

    files = client().tot(
        COMANDES,
        select="DocEntry,DocNum,Series",
        filtre=f"U_SEIOrdCargId eq {docentry_carrega}",
        ordre="Series,DocNum",
    )
    return [
        {
            "eje_ejercicio": eje or "SAP",
            "sal_codigo": str(f.get("Series") if f.get("Series") is not None else 0),
            "cpa_albara": str(f.get("DocNum")),
            "det_tipo": "A",
        }
        for f in files
    ]


# =============================================================================
# Previsualitzacio de carrega (comandes + linies + kg)
# =============================================================================
def resum_carrega(eje: str, sca: str, car: str) -> dict:
    """Contingut d'una carrega: comandes amb les seves linies i els totals.

    Dues o tres crides, contra les tres consultes del SQL:

      1. `Orders` amb `DocumentLines` al `$select`. Les linies venen INLINE
         perque `DocumentLines` es una propietat complexa de col·leccio, no una
         navigation property: per aixo `$expand` la rebutja pero `$select` la
         serveix. Es l'unica manera d'evitar una crida per comanda.
      2. `BusinessPartners` amb `BPAddresses`, que pel mateix mecanisme ve
         inline i substitueix OCRD *i* CRD1 en una sola crida.
      3. La unitat de venda, de la cache d'articles (normalment 0 crides).
    """
    try:
        docentry_carrega = int(car)
    except (TypeError, ValueError):
        return {"comandes": [], "total_sacs": 0, "total_kg": 0.0}

    c = client()
    comandes = c.tot(
        COMANDES,
        select="DocEntry,DocNum,Series,CardCode,ShipToCode,DocumentLines",
        filtre=f"U_SEIOrdCargId eq {docentry_carrega}",
        ordre="Series,DocNum",
    )
    if not comandes:
        return {"comandes": [], "total_sacs": 0, "total_kg": 0.0}

    # --- Clients i poblacio d'enviament ---------------------------------
    # El SQL busca la ciutat a CRD1 per (CardCode, Address) amb AdresType='S',
    # i si no la troba cau a OCRD.City. Aqui les dues taules arriben juntes:
    # BPAddresses porta AddressName (= CRD1.Address) i AddressType
    # ('bo_ShipTo' = 'S').
    codis_cli = sorted({(o.get("CardCode") or "").strip()
                        for o in comandes if (o.get("CardCode") or "").strip()})
    noms_cli: dict[str, str] = {}
    ciutat_cli: dict[str, str] = {}
    adreces: dict[tuple[str, str], str] = {}
    if codis_cli:
        for tros in od.trossos(codis_cli):
            for bp in c.tot(INTERLOCUTORS,
                            select="CardCode,CardName,City,BPAddresses",
                            filtre=od.qualsevol_de("CardCode", tros)):
                codi = (bp.get("CardCode") or "").strip()
                noms_cli[codi] = (bp.get("CardName") or "").strip()
                ciutat_cli[codi] = (bp.get("City") or "").strip()
                for a in bp.get("BPAddresses") or []:
                    if a.get("AddressType") != "bo_ShipTo":
                        continue
                    nom_adr = (a.get("AddressName") or "").strip()
                    if nom_adr:
                        adreces[(codi, nom_adr)] = (a.get("City") or "").strip()

    # --- Unitats de venda, per decidir si una linia es palletitzable ------
    codis_art = {(l.get("ItemCode") or "").strip()
                 for o in comandes for l in (o.get("DocumentLines") or [])
                 if (l.get("ItemCode") or "").strip()}
    unitats_art = cache_articles.unitats_venda(sorted(codis_art)) if codis_art else {}

    # --- Mateixa agregacio que fa el SQL en Python ------------------------
    total_sacs = 0
    total_kg = 0.0
    out_com: list[dict] = []
    for o in comandes:
        linies: list[dict] = []
        for l in sorted((o.get("DocumentLines") or []),
                        key=lambda x: x.get("LineNum") or 0):
            art_codi = (l.get("ItemCode") or "").strip()
            # COALESCE(NULLIF(PackQty, 0), Quantity)
            pack = float(l.get("PackageQuantity") or 0)
            quan = float(l.get("Quantity") or 0)
            unitats = pack if pack else quan
            # El SQL fa LEFT JOIN amb OITM: una linia sense article a OITM
            # arriba amb tunitat buida, i una tunitat buida compta com a
            # palletitzable. Ho repliquem amb el `.get(..., "")`.
            tun = (unitats_art.get(art_codi) or "").strip()
            linies.append({
                "art_codi": art_codi,
                "art_descrip": (l.get("ItemDescription") or "").strip(),
                "sacs": int(unitats),
                "quan": quan,
                "tunitat": tun,
                "kg": round(quan if quan > 0 else 0.0, 2),
                "palletitzable": _es_palletizable(tun, unitats),
            })

        a_sacs = sum(int(x["sacs"]) for x in linies if x["palletitzable"])
        a_kg = sum(float(x["kg"]) for x in linies)
        total_sacs += a_sacs
        total_kg += a_kg

        cli_codi = (o.get("CardCode") or "").strip()
        adr_codi = (o.get("ShipToCode") or "").strip()
        pobla = adreces.get((cli_codi, adr_codi), "") or ciutat_cli.get(cli_codi, "")
        series = o.get("Series") if o.get("Series") is not None else 0
        out_com.append({
            "comanda": f"{series}/{o.get('DocNum')}",
            "det_tipo": "A",
            "cli_codi": cli_codi,
            "cli_nom": noms_cli.get(cli_codi, ""),
            "pobla": pobla,
            "total_sacs": a_sacs,
            "total_kg": round(a_kg, 2),
            "linies": linies,
        })

    # Mateixa ordenacio que el SQL: les comandes sense poblacio, al final.
    # S'usa .upper() i no la clau de collation a proposit: aquesta ordenacio ja
    # es feia en Python abans de la migracio i ha de donar el mateix.
    out_com.sort(key=lambda x: (1 if not (x.get("pobla") or "") else 0,
                               str(x.get("pobla") or "").upper(),
                               str(x.get("cli_nom") or "").upper()))
    return {"comandes": out_com, "total_sacs": total_sacs, "total_kg": round(total_kg, 2)}


# =============================================================================
# Llistat de carregues
# =============================================================================
# Camps de la capcalera que necessita el llistat. Sense $select el Service
# Layer torna les 40 propietats de l'entitat.
_CAMPS_CAPCALERA = (
    "DocEntry,DocNum,Series,CreateDate,U_SEINomCarg,U_SEIDataS,U_SEIHoraS,"
    "U_SEIEstado,U_SEITransp,U_SEIMatric,U_SEIPesoC,U_SEIComent"
)

# Cache del nom dels transportistes: substitueix el LEFT JOIN amb la UDT.
# Es una taula petita i gairebe estatica.
_noms_transp: dict[str, str] | None = None
_noms_transp_a: float = 0.0


def _noms_transportistes() -> dict[str, str]:
    global _noms_transp, _noms_transp_a
    ttl = float(os.environ.get("SAP_SL_CACHE_TRANSP_TTL", "900"))
    if _noms_transp is None or (time.monotonic() - _noms_transp_a) > ttl:
        files = client().tot(TRANSPORTISTES, select="Code,Name")
        _noms_transp = {(f.get("Code") or "").strip(): (f.get("Name") or "").strip()
                        for f in files}
        _noms_transp_a = time.monotonic()
    return _noms_transp


def _data(valor) -> str | None:
    """`2026-04-22T00:00:00Z` -> `2026-04-22`.

    Agafem els 10 primers caracters i prou: la `Z` que posa el Service Layer es
    falsa (son dates locals sense zona) i qualsevol conversio de zona
    desplacaria el dia respecte del que retorna el SQL.
    """
    if not valor:
        return None
    return str(valor)[:10]


def _hora(valor) -> str | None:
    """`13:30:00` (Edm.Time del SL) -> `13:30`.

    Al SQL el camp es un smallint HHMM i el converteix `_fmt_hora`; pel Service
    Layer arriba ja com a hora, aixi que nomes cal escurcar-la.
    """
    if not valor:
        return None
    parts = str(valor).split(":")
    if len(parts) < 2:
        return None
    try:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    except ValueError:
        return None


def llistar_carregues(
    desde: str,
    fins: str,
    tra_codis: list[str] | str | None = None,
    estat: int | None = None,
    art_codi: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict:
    """Llista carregues. Dues crides al Service Layer i una consulta a PostgreSQL.

    Tres coses no es poden fer al Service Layer i es fan aqui:

    1. **L'ordenacio.** El SQL ordena per `COALESCE(U_SEIDataS, CreateDate)
       DESC` i `$orderby` no accepta funcions. Per tant ens portem la finestra
       de dates sencera (el filtre SI es expressable) i ordenem i paginem en
       Python. La UI sempre envia un rang, de manera que el conjunt esta fitat.

    2. **Els filtres d'igualtat de text** (estat i transportista). El SQL
       compara amb `UPPER(RTRIM(...))` i amb la semantica de farciment d'ANSI;
       el Service Layer no te `toupper` ni `trim`. Fer-los aqui garanteix la
       mateixa semantica exacta i no costa res, perque el camp ja ve al
       payload.

    3. **Els quatre camps derivats i el filtre per article**, que surten de la
       taula d'agregats de PostgreSQL. Vegeu
       `db/migrations/006_agregats_carrega.sql`.
    """
    desde_d = datetime.strptime(desde, "%Y-%m-%d").date()
    fins_d = datetime.strptime(fins, "%Y-%m-%d").date() + timedelta(days=1)
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))

    if isinstance(tra_codis, str):
        tra_codis = [c.strip() for c in tra_codis.split(",") if c.strip()]
    elif tra_codis is None:
        tra_codis = []

    # No filtrem per `Canceled`, igual que el SQL: SAP l'ignora a la finestra
    # "Ordenes de Carga Abiertas" i hi mostra fins i tot els cancel·lats si
    # l'estat es planificada.
    filtre = od.finestra_coalesce("U_SEIDataS", "CreateDate", desde_d, fins_d)
    capceleres = client().tot(ORDRES, select=_CAMPS_CAPCALERA,
                              filtre=filtre, ordre="DocEntry")

    maxim = int(os.environ.get("SL_MAX_CAPCALERES", "5000"))
    if len(capceleres) > maxim:
        raise SLError(
            f"El rang demanat torna {len(capceleres)} carregues i el maxim es "
            f"{maxim}. Redueix el rang de dates."
        )

    # --- Filtres que es fan aqui per tenir la semantica exacta del SQL ----
    if estat is not None:
        estat_c = _estat_int_to_char(int(estat))
        if estat_c:
            capceleres = [h for h in capceleres
                          if (h.get("U_SEIEstado") or "").strip().upper() == estat_c]
    if tra_codis:
        vols = {c.strip() for c in tra_codis}
        capceleres = [h for h in capceleres
                      if (h.get("U_SEITransp") or "").strip() in vols]
    if art_codi:
        amb_article = agregats.carregues_amb_article(art_codi)
        capceleres = [h for h in capceleres if int(h["DocEntry"]) in amb_article]

    # --- Ordenacio i paginacio -------------------------------------------
    def clau(h):
        efectiva = h.get("U_SEIDataS") or h.get("CreateDate") or ""
        return (str(efectiva), int(h.get("DocNum") or 0))

    capceleres.sort(key=clau, reverse=True)
    total = len(capceleres)
    pagina = capceleres[offset:offset + limit]

    # --- Camps derivats, de la taula d'agregats ---------------------------
    docentries = [int(h["DocEntry"]) for h in pagina]
    derivats = agregats.per_carrega(docentries)
    neutre = {"kg_total": 0.0, "num_comandes": 0,
              "palletitzable": False, "is_granel": False}
    noms = _noms_transportistes()

    items = []
    for h in pagina:
        series = h.get("Series") if h.get("Series") is not None else 0
        docentry = int(h["DocEntry"])
        tra_codi = (h.get("U_SEITransp") or "").strip()
        d = derivats.get(docentry, neutre)
        coment = h.get("U_SEIComent") or ""
        items.append({
            "eje_ejercicio": "SAP",
            "sca_serie": str(series),
            "car_numero": str(docentry),
            "carrega_id": _carrega_id(series, docentry),
            "car_descripcion": (h.get("U_SEINomCarg") or "").strip(),
            "car_fecha": _data(h.get("CreateDate")),
            "car_fecsalida": _data(h.get("U_SEIDataS")),
            "car_fecsalida_hora": _hora(h.get("U_SEIHoraS")),
            # SAP no te data d'arribada: None per compatibilitat amb KAIS.
            "car_fecllegada": None,
            "car_fecllegada_hora": None,
            "car_estat": _estat_char_to_int(h.get("U_SEIEstado")) or 0,
            "tra_codi": tra_codi,
            "transportista": noms.get(tra_codi, ""),
            "car_matricula": (h.get("U_SEIMatric") or "").strip(),
            # SAP no te camp conductor.
            "car_nomconductor": "",
            "car_pesonetocarga": (float(h["U_SEIPesoC"])
                                  if h.get("U_SEIPesoC") is not None else 0.0),
            "car_pesoteorico": 0.0,
            # El SQL fa CAST(... AS varchar(500)): les observacions es trunquen.
            "car_observaciones": str(coment)[:500].strip(),
            "palletitzable": bool(d["palletitzable"]),
            "is_granel": bool(d["is_granel"]),
            "kg_total": float(d["kg_total"]),
            "num_comandes": int(d["num_comandes"]),
        })
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}
