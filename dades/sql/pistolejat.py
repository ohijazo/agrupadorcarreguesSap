"""Dades del pistolejat per SQL Server directe. Contracte a `dades/pistolejat.py`."""
from __future__ import annotations

from dades.sql.carregues import connectar

# SQL Server admet fins a 2100 parametres per consulta; anem molt per sota.
_TROS = 500


def _trossos(valors: list[int]):
    for n in range(0, len(valors), _TROS):
        yield valors[n:n + _TROS]


def obtenir_dades_pistolejat(carregues: list[int], incloure_tancades: bool = False,
                             amb_lots: bool = False, amb_trasllats: bool = False) -> dict:
    """Linies obertes de les comandes obertes d'aquestes carregues, les
    lectures de `@SEIOPIC` encara sense albara, i l'ultim estat de cada comanda.

    `carregues` son DocEntry de `@SEI_ORDENCARGA`. Amb `incloure_tancades`
    tambe hi surten les comandes i linies tancades (no les cancel·lades): una
    linia amb albara te `kg_oberts = 0` i per tant es dona per feta.

    Amb `amb_lots` hi ha tambe `lots`: els lots pistolejats de cada linia
    (amb albara o sense; no els d'albarans cancel·lats), per a "Preparacio de
    comanda". Es una lectura mes de `@SEIOPIC`: nomes qui la necessita.

    `albarans`: els albarans no cancel·lats de cada comanda ({comanda,
    albara, docnum}), via les lectures de `@SEIOPIC` que hi apunten.
    """
    ids = sorted({int(c) for c in carregues or []})
    if not ids:
        return {"comandes": [], "pistolejats": [], "pistolejats_cancelats": [], "estats": {},
                "albarans": []}

    comandes: dict[int, dict] = {}
    pistolejats: list[dict] = []
    cancelats: list[dict] = []
    albarans: list[dict] = []
    lots: list[dict] = []
    estats: dict[int, str] = {}

    conn = connectar()
    try:
        for tros in _trossos(ids):
            ph = ",".join(["?"] * len(tros))
            rows = conn.execute(f"""
                SELECT o.DocEntry, o.DocNum, o.U_SEIOrdCargId AS carrega,
                       RTRIM(o.CardCode) AS cli_codi, RTRIM(o.CardName) AS cli_nom,
                       l.LineNum, RTRIM(l.ItemCode) AS art_codi,
                       RTRIM(l.Dscription) AS art_descrip, RTRIM(l.unitMsr) AS unitat,
                       l.PackQty, l.InvQty,
                       -- Granel: unitat GRA/KG/KGS (a produccio el granel es
                       -- 'KGS'), o propietat 5 ("Es Granel") si la unitat no
                       -- es de sacs. Es compta en kg, mai en sacs: amb
                       -- SalPackUn 1, PackQty son els kg i semblarien sacs.
                       CASE WHEN (UPPER(RTRIM(ISNULL(l.unitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (i.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(l.unitMsr, ''))) NOT LIKE 'S[0-9]%'))
                            THEN 1 ELSE 0 END AS granel,
                       -- Una linia tancada a ma (sense albara) conserva
                       -- l'OpenInvQty: no queda res per preparar.
                       CASE WHEN l.LineStatus = 'O' THEN l.OpenInvQty ELSE 0 END AS OpenInvQty
                FROM   ORDR o WITH (NOLOCK)
                JOIN   RDR1 l WITH (NOLOCK) ON l.DocEntry = o.DocEntry
                LEFT   JOIN OITM i WITH (NOLOCK) ON i.ItemCode = l.ItemCode
                WHERE  o.U_SEIOrdCargId IN ({ph})
                  AND  o.CANCELED = 'N'
                  {"" if incloure_tancades else "AND o.DocStatus = 'O' AND l.LineStatus = 'O'"}
                ORDER  BY o.DocEntry, l.LineNum
            """, *tros).fetchall()
            for r in rows:
                c = comandes.setdefault(r.DocEntry, {
                    "docentry": int(r.DocEntry),
                    "docnum": r.DocNum,
                    "carrega": int(r.carrega),
                    "cli_codi": r.cli_codi or "",
                    "cli_nom": (r.cli_nom or "").strip(),
                    "linies": [],
                })
                c["linies"].append({
                    "linia": int(r.LineNum),
                    "art_codi": r.art_codi or "",
                    "art_descrip": (r.art_descrip or "").strip(),
                    "unitat": r.unitat or "",
                    "granel": bool(r.granel),
                    "sacs": float(r.PackQty or 0),
                    "kg": float(r.InvQty or 0),
                    "kg_oberts": float(r.OpenInvQty or 0),
                })

        docs = sorted(comandes)
        for tros in _trossos(docs):
            ph = ",".join(["?"] * len(tros))
            for r in conn.execute(f"""
                SELECT p.U_BaseEntry AS comanda, p.U_BaseLine AS linia,
                       SUM(p.U_Quantity) AS sacs, SUM(p.U_InvQty) AS kg
                FROM   [@SEIOPIC] p WITH (NOLOCK)
                WHERE  p.U_BaseObject = 17
                  AND  p.U_TargetEntry IS NULL
                  AND  p.U_BaseEntry IN ({ph})
                GROUP  BY p.U_BaseEntry, p.U_BaseLine
            """, *tros).fetchall():
                pistolejats.append({
                    "comanda": int(r.comanda),
                    "linia": int(r.linia),
                    "sacs": round(float(r.sacs or 0), 6),
                    "kg": round(float(r.kg or 0), 6),
                })

            # Lectures d'un albara que despres es va cancel·lar: es queden a
            # @SEIOPIC apuntant-hi. No compten com a pistolejat (la linia
            # torna a estar oberta i l'SGA demana tornar a pistolejar), pero
            # la mercaderia pot ser al palet: es tornen a part per avisar-ne.
            for r in conn.execute(f"""
                SELECT p.U_BaseEntry AS comanda, p.U_BaseLine AS linia,
                       p.U_TargetEntry AS albara, d.DocNum AS docnum,
                       SUM(p.U_Quantity) AS sacs, SUM(p.U_InvQty) AS kg
                FROM   [@SEIOPIC] p WITH (NOLOCK)
                JOIN   ODLN d WITH (NOLOCK) ON d.DocEntry = p.U_TargetEntry
                WHERE  p.U_BaseObject = 17
                  AND  p.U_TargetType = 15
                  AND  d.CANCELED = 'Y'
                  AND  p.U_BaseEntry IN ({ph})
                GROUP  BY p.U_BaseEntry, p.U_BaseLine, p.U_TargetEntry, d.DocNum
            """, *tros).fetchall():
                cancelats.append({
                    "comanda": int(r.comanda),
                    "linia": int(r.linia),
                    "albara": int(r.albara),
                    "docnum": int(r.docnum),
                    "sacs": round(float(r.sacs or 0), 6),
                    "kg": round(float(r.kg or 0), 6),
                })

            # Albarans vius de cada comanda (nomes se'n fa un per comanda):
            # una comanda amb albara ja no es pendent de pistolejar. Pels
            # lectures de l'SGA i tambe per la linia de l'albara (DLN1): els
            # de granel es fan a SAP sense pistolejar (usuari MES, carrega 13).
            for r in conn.execute(f"""
                SELECT p.U_BaseEntry AS comanda, d.DocEntry AS albara, d.DocNum AS docnum
                FROM   [@SEIOPIC] p WITH (NOLOCK)
                JOIN   ODLN d WITH (NOLOCK) ON d.DocEntry = p.U_TargetEntry
                WHERE  p.U_BaseObject = 17
                  AND  p.U_TargetType = 15
                  AND  d.CANCELED = 'N'
                  AND  p.U_BaseEntry IN ({ph})
                UNION
                SELECT dl.BaseEntry, d.DocEntry, d.DocNum
                FROM   DLN1 dl WITH (NOLOCK)
                JOIN   ODLN d WITH (NOLOCK) ON d.DocEntry = dl.DocEntry
                WHERE  dl.BaseType = 17
                  AND  d.CANCELED = 'N'
                  AND  dl.BaseEntry IN ({ph})
            """, *tros, *tros).fetchall():
                albarans.append({
                    "comanda": int(r.comanda),
                    "albara": int(r.albara),
                    "docnum": int(r.docnum),
                })

            # Lots (U_ManagedBy 10000044 = per lots, OBTN). Les lectures d'un
            # albara cancel·lat no hi son: ja surten a l'avis de cancel·lat.
            if amb_lots:
                for r in conn.execute(f"""
                    SELECT p.U_BaseEntry AS comanda, p.U_BaseLine AS linia,
                           RTRIM(b.DistNumber) AS lot,
                           CASE WHEN p.U_TargetEntry IS NULL THEN 0 ELSE 1 END AS albara,
                           SUM(p.U_Quantity) AS sacs, SUM(p.U_InvQty) AS kg
                    FROM   [@SEIOPIC] p WITH (NOLOCK)
                    JOIN   OBTN b WITH (NOLOCK) ON b.AbsEntry = p.U_MdAbsEntry
                    LEFT   JOIN ODLN d WITH (NOLOCK)
                           ON d.DocEntry = p.U_TargetEntry AND p.U_TargetType = 15
                    WHERE  p.U_BaseObject = 17
                      AND  p.U_ManagedBy = 10000044
                      AND  ISNULL(d.CANCELED, 'N') <> 'Y'
                      AND  p.U_BaseEntry IN ({ph})
                    GROUP  BY p.U_BaseEntry, p.U_BaseLine, b.DistNumber,
                              CASE WHEN p.U_TargetEntry IS NULL THEN 0 ELSE 1 END
                """, *tros).fetchall():
                    lots.append({
                        "comanda": int(r.comanda),
                        "linia": int(r.linia),
                        "lot": r.lot or "",
                        "albara": bool(r.albara),
                        "sacs": round(float(r.sacs or 0), 6),
                        "kg": round(float(r.kg or 0), 6),
                    })

            # Ultim estat = la fila amb el Code mes alt (autoincremental). Code
            # es text: s'ordena com a numero ("10" despres de "9"), com fa el
            # Service Layer, i en una sola passada (sense subconsulta per fila).
            for r in conn.execute(f"""
                SELECT comanda, estat FROM (
                    SELECT e.U_SEIDocEntry AS comanda, RTRIM(e.U_SEIEstado) AS estat,
                           ROW_NUMBER() OVER (PARTITION BY e.U_SEIDocEntry
                                              ORDER BY TRY_CAST(e.Code AS bigint) DESC, e.Code DESC) AS n
                    FROM   [@SEIESTATSCOM] e WITH (NOLOCK)
                    WHERE  e.U_SEIDocEntry IN ({ph})
                ) x
                WHERE n = 1
            """, *tros).fetchall():
                estats[int(r.comanda)] = r.estat or ""
        if amb_trasllats:
            _afegeix_trasllats(conn, ids, incloure_tancades, comandes, pistolejats, albarans)
            docs = sorted(comandes)
    finally:
        conn.close()

    return {
        "comandes": [comandes[d] for d in docs],
        "pistolejats": sorted(pistolejats, key=lambda p: (p["comanda"], p["linia"])),
        "pistolejats_cancelats": sorted(cancelats, key=lambda p: (p["comanda"], p["linia"], p["albara"])),
        "estats": estats,
        "albarans": sorted(albarans, key=lambda a: (a["comanda"], a["albara"])),
        **({"lots": sorted(lots, key=lambda p: (p["comanda"], p["linia"], p["albara"], p["lot"]))}
           if amb_lots else {}),
    }


# --- Sol·licituds de trasllat (OWTQ) ------------------------------------------
# Una carrega pot portar trasllats a un altre magatzem nostre (01 -> 05
# Mallorca). L'SGA els pistoleja igual que les comandes: lectures a @SEIOPIC
# amb U_BaseObject 1250000001 i, en acabar, un trasllat d'estoc (OWTR, 67) que
# fa de "albara". Es tornen com una comanda mes, amb DocEntry NEGATIU (els
# DocEntry d'OWTQ i d'ORDR es repeteixen) i `docnum` "Trasllat N", que es com
# els anomena el detall de la carrega. No porten estat de @SEIESTATSCOM: alla
# U_SEIDocEntry es d'una comanda.
OBJ_SOL_TRASLLAT = 1250000001
OBJ_TRASLLAT = 67


def _afegeix_trasllats(conn, carregues, incloure_tancades, comandes, pistolejats, albarans):
    from dades.sql.carregues import _sacs_trasllat

    for tros in _trossos(carregues):
        ph = ",".join(["?"] * len(tros))
        for r in conn.execute(f"""
            SELECT q.DocEntry, q.DocNum, q.U_SEIOrdCargId AS carrega,
                   RTRIM(q.ToWhsCode) AS cli_codi, RTRIM(w.WhsName) AS cli_nom,
                   l.LineNum, RTRIM(l.ItemCode) AS art_codi, RTRIM(l.Dscription) AS art_descrip,
                   RTRIM(i.SalUnitMsr) AS unitat, l.PackQty, l.InvQty,
                   CASE WHEN (UPPER(RTRIM(ISNULL(i.SalUnitMsr, ''))) IN ('GRA', 'KG', 'KGS') OR (i.QryGroup5 = 'Y' AND UPPER(RTRIM(ISNULL(i.SalUnitMsr, ''))) NOT LIKE 'S[0-9]%'))
                        THEN 1 ELSE 0 END AS granel,
                   CASE WHEN l.LineStatus = 'O' THEN l.OpenInvQty ELSE 0 END AS OpenInvQty
            FROM   OWTQ q WITH (NOLOCK)
            JOIN   WTQ1 l WITH (NOLOCK) ON l.DocEntry = q.DocEntry
            LEFT   JOIN OITM i WITH (NOLOCK) ON i.ItemCode = l.ItemCode
            LEFT   JOIN OWHS w WITH (NOLOCK) ON w.WhsCode = q.ToWhsCode
            WHERE  q.U_SEIOrdCargId IN ({ph})
              AND  q.CANCELED = 'N'
              {"" if incloure_tancades else "AND q.DocStatus = 'O' AND l.LineStatus = 'O'"}
            ORDER  BY q.DocEntry, l.LineNum
        """, *tros).fetchall():
            kg = float(r.InvQty or 0)
            paq = float(r.PackQty or 0)
            c = comandes.setdefault(-int(r.DocEntry), {
                "docentry": -int(r.DocEntry),
                "docnum": f"Trasllat {r.DocNum}",
                "carrega": int(r.carrega),
                "cli_codi": r.cli_codi or "",
                "cli_nom": (r.cli_nom or "").strip(),
                "linies": [],
            })
            c["linies"].append({
                "linia": int(r.LineNum),
                "art_codi": r.art_codi or "",
                "art_descrip": (r.art_descrip or "").strip(),
                "unitat": r.unitat or "",
                "granel": bool(r.granel),
                # Al trasllat PackQty sol ser 0: els sacs surten de la unitat.
                "sacs": paq if paq > 0 else float(_sacs_trasllat(kg, r.unitat)),
                "kg": kg,
                "kg_oberts": float(r.OpenInvQty or 0),
            })

    docs = sorted(-d for d in comandes if d < 0)
    for tros in _trossos(docs):
        ph = ",".join(["?"] * len(tros))
        for r in conn.execute(f"""
            SELECT p.U_BaseEntry AS doc, p.U_BaseLine AS linia,
                   SUM(p.U_Quantity) AS sacs, SUM(p.U_InvQty) AS kg
            FROM   [@SEIOPIC] p WITH (NOLOCK)
            WHERE  p.U_BaseObject = {OBJ_SOL_TRASLLAT}
              AND  p.U_TargetEntry IS NULL
              AND  p.U_BaseEntry IN ({ph})
            GROUP  BY p.U_BaseEntry, p.U_BaseLine
        """, *tros).fetchall():
            pistolejats.append({"comanda": -int(r.doc), "linia": int(r.linia),
                                "sacs": round(float(r.sacs or 0), 6),
                                "kg": round(float(r.kg or 0), 6)})
        # El trasllat fet (OWTR) es busca per la linia (WTR1.BaseEntry): hi
        # es tant si l'ha fet l'SGA com si s'ha fet a ma a SAP.
        for r in conn.execute(f"""
            SELECT DISTINCT tl.BaseEntry AS doc, t.DocEntry AS albara, t.DocNum AS docnum
            FROM   WTR1 tl WITH (NOLOCK)
            JOIN   OWTR t WITH (NOLOCK) ON t.DocEntry = tl.DocEntry
            WHERE  tl.BaseType = {OBJ_SOL_TRASLLAT}
              AND  t.CANCELED = 'N'
              AND  tl.BaseEntry IN ({ph})
        """, *tros).fetchall():
            albarans.append({"comanda": -int(r.doc), "albara": int(r.albara),
                             "docnum": int(r.docnum)})
    pistolejats.sort(key=lambda p: (p["comanda"], p["linia"]))
    albarans.sort(key=lambda a: (a["comanda"], a["albara"]))
