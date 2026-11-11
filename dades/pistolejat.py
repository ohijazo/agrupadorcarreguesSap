"""Calcul dels articles pendents de pistolejar, independent del backend.

El pistolejat el registra l'addon SEIDOR / SGA a `@SEIOPIC` ("Articulos
recogidos"): una fila per cada lectura d'una linia de comanda, amb lot i
quantitat. Quan l'SGA crea l'albara, la fila queda lligada a l'albara
(`U_TargetType=15`, `U_TargetEntry`) i la quantitat oberta de la linia de
comanda (`RDR1.OpenInvQty`) ja baixa. Per tant:

    pendent = OpenInvQty - suma(U_InvQty de les lectures SENSE albara)

Les lectures amb albara no es resten: ja estan descomptades de l'OpenInvQty. I
si l'albara es cancel·la, l'OpenInvQty torna a pujar i la lectura (que apunta a
un albara cancel·lat) tampoc no ha de comptar. Es compara en unitat
d'inventari (kg): `U_Quantity` va en unitat de venda (sacs).

Vegeu `docs/descoberta_pistolejat_albarans.md`.

`progres_agrupacio` fa servir el mateix calcul per a la preparacio d'una
agrupacio: el pistolejat de l'SGA substitueix el checklist manual. Alla les
dades porten tambe les linies tancades (`incloure_tancades=True`): una linia
amb albara te OpenInvQty 0 i surt com a feta.

Aquest modul no toca SAP: rep files ja normalitzades pels backends
(`dades/sql/pistolejat.py`, `dades/sl/pistolejat.py`) i es pot provar sol.
"""
from __future__ import annotations

# Per sota d'aixo (en kg) una linia es dona per completa: les quantitats de SAP
# venen amb 6 decimals i les restes poden deixar residus.
_EPSILON = 1e-6

ESTAT_PENDENT = "pendent"
ESTAT_PARCIAL = "parcial"
ESTAT_COMPLET = "complet"

# `car_estat` de llistar_carregues: 2 = sortida.
_CARREGA_SORTIDA = 2


def _linia(l: dict, pist: dict | None) -> dict:
    kg = float(l.get("kg") or 0)
    sacs = float(l.get("sacs") or 0)
    kg_oberts = max(float(l.get("kg_oberts") or 0), 0.0)
    kg_pist = float((pist or {}).get("kg") or 0)
    sacs_pist = float((pist or {}).get("sacs") or 0)
    kg_pend = max(kg_oberts - kg_pist, 0.0)

    if kg_pend <= _EPSILON:
        estat = ESTAT_COMPLET
    elif kg_pist > _EPSILON:
        estat = ESTAT_PARCIAL
    else:
        estat = ESTAT_PENDENT

    # Sacs: els de la comanda (PackQty) escalats a la part oberta. Les linies
    # sense sacs (granel, unitats soltes amb PackQty 0) no en tenen. Al granel
    # (propietat 5 o unitat GRA/KG/KGS) PackQty son kg: tampoc no son sacs.
    if sacs > 0 and kg > 0 and not l.get("granel"):
        sacs_oberts = round(kg_oberts * sacs / kg, 2)
        sacs_pend = round(max(sacs_oberts - sacs_pist, 0.0), 2)
    else:
        sacs_oberts = sacs_pend = None

    return {
        "linia": int(l.get("linia") or 0),
        "art_codi": l.get("art_codi") or "",
        "art_descrip": l.get("art_descrip") or "",
        "unitat": l.get("unitat") or "",
        "granel": bool(l.get("granel")),
        "kg_oberts": round(kg_oberts, 3),
        "kg_pistolejats": round(kg_pist, 3),
        "kg_pendents": round(kg_pend, 3),
        "sacs_oberts": sacs_oberts,
        "sacs_pistolejats": round(sacs_pist, 2),
        "sacs_pendents": sacs_pend,
        "estat": estat,
    }


def _totals(linies: list[dict]) -> dict:
    kg_oberts = sum(l["kg_oberts"] for l in linies)
    kg_pist = sum(min(l["kg_pistolejats"], l["kg_oberts"]) for l in linies)
    return {
        "n_linies": len(linies),
        "n_pendents": sum(1 for l in linies if l["estat"] != ESTAT_COMPLET),
        "kg_oberts": round(kg_oberts, 3),
        "kg_pendents": round(sum(l["kg_pendents"] for l in linies), 3),
        "sacs_pendents": round(sum(l["sacs_pendents"] or 0 for l in linies), 2),
        "percent": round(100 * kg_pist / kg_oberts) if kg_oberts > _EPSILON else 100,
    }


def _suma_pistolejats(dades: dict) -> dict[tuple[int, int], dict]:
    pist: dict[tuple[int, int], dict] = {}
    for p in dades.get("pistolejats") or []:
        clau = (int(p["comanda"]), int(p["linia"]))
        acc = pist.setdefault(clau, {"kg": 0.0, "sacs": 0.0})
        acc["kg"] += float(p.get("kg") or 0)
        acc["sacs"] += float(p.get("sacs") or 0)
    return pist


def _suma_cancelats(dades: dict) -> dict[tuple[int, int], dict]:
    """Lectures d'albarans cancel·lats per linia de comanda (vegeu
    `pistolejats_cancelats`). Nomes per avisar: no resten del pendent."""
    out: dict[tuple[int, int], dict] = {}
    for p in dades.get("pistolejats_cancelats") or []:
        acc = out.setdefault((int(p["comanda"]), int(p["linia"])),
                             {"kg": 0.0, "sacs": 0.0, "albarans": set()})
        acc["kg"] += float(p.get("kg") or 0)
        acc["sacs"] += float(p.get("sacs") or 0)
        acc["albarans"].add(int(p.get("docnum") or p.get("albara") or 0))
    return out


def _albarans_per_comanda(dades: dict) -> dict[int, list[int]]:
    """{docentry_comanda: [docnum dels albarans no cancel·lats]}. Nomes es
    fa un albara per comanda: si en te, la comanda ja no es pendent."""
    out: dict[int, set[int]] = {}
    for a in dades.get("albarans") or []:
        out.setdefault(int(a["comanda"]), set()).add(int(a.get("docnum") or a.get("albara") or 0))
    return {k: sorted(v) for k, v in out.items()}


def _avis_cancelat(acc: dict | None) -> dict | None:
    if not acc or acc["kg"] <= _EPSILON:
        return None
    return {"kg": round(acc["kg"], 3), "sacs": round(acc["sacs"], 2),
            "albarans": sorted(acc["albarans"])}


def construir(
    carregues: list[dict],
    dades: dict,
    nomes_pendents: bool = True,
) -> dict:
    """Arbre carrega -> comanda -> linia amb el pendent de cada linia.

    `carregues`: items de `llistar_carregues`.
    `dades`: el que retorna `obtenir_dades_pistolejat`, amb tres claus:
        comandes:    [{docentry, docnum, carrega, cli_codi, cli_nom,
                       linies: [{linia, art_codi, art_descrip, unitat,
                                 sacs, kg, kg_oberts}]}]
                     nomes comandes obertes i linies obertes.
        pistolejats: [{comanda, linia, sacs, kg}] lectures sense albara,
                     ja sumades per linia o no (aqui se sumen igualment).
        estats:      {docentry_comanda: ultim estat de @SEIESTATSCOM}
        pistolejats_cancelats (opcional): lectures d'albarans cancel·lats;
                     cada linia en porta l'avis a `cancelat` (o None).
        albarans (opcional): [{comanda, albara, docnum}] albarans no
                     cancel·lats de cada comanda; van a `albarans` de la comanda.

    Amb `nomes_pendents`, es treuen les linies completes, les comandes que ja
    tenen albara (se'n fa un per comanda, encara que en quedin linies obertes),
    les comandes i carregues que queden buides, i les carregues ja sortides.
    """
    pist = _suma_pistolejats(dades)
    canc = _suma_cancelats(dades)
    estats = dades.get("estats") or {}
    lots = _lots_per_linia(dades)
    albarans = _albarans_per_comanda(dades)

    per_carrega: dict[int, list[dict]] = {}
    for c in dades.get("comandes") or []:
        alb = albarans.get(int(c["docentry"]), [])
        if nomes_pendents and alb:
            continue
        linies = []
        for l in sorted(c.get("linies") or [], key=lambda x: int(x.get("linia") or 0)):
            clau = (int(c["docentry"]), int(l.get("linia") or 0))
            lc = _linia(l, pist.get(clau))
            lc["cancelat"] = _avis_cancelat(canc.get(clau))
            if "lots" in dades:
                lc["lots"] = lots.get(clau, [])
            linies.append(lc)
        if nomes_pendents:
            linies = [l for l in linies if l["estat"] != ESTAT_COMPLET]
        if not linies:
            continue
        per_carrega.setdefault(int(c["carrega"]), []).append({
            "docentry": int(c["docentry"]),
            "docnum": c.get("docnum"),
            "cli_codi": c.get("cli_codi") or "",
            "cli_nom": c.get("cli_nom") or "",
            "estat_comanda": estats.get(int(c["docentry"])) or "",
            "albarans": alb,
            "linies": linies,
            "totals": _totals(linies),
        })

    out: list[dict] = []
    for car in carregues:
        try:
            docentry = int(car.get("car_numero"))
        except (TypeError, ValueError):
            continue
        if nomes_pendents and car.get("car_estat") == _CARREGA_SORTIDA:
            continue
        comandes = sorted(per_carrega.get(docentry, []), key=lambda x: str(x["docnum"]))
        if not comandes:
            continue
        totes = [l for cm in comandes for l in cm["linies"]]
        out.append({
            "carrega_id": car.get("carrega_id"),
            "docentry": docentry,
            "nom": car.get("car_descripcion") or "",
            "data_sortida": car.get("car_fecsalida"),
            "hora_sortida": car.get("car_fecsalida_hora"),
            "transportista": car.get("transportista") or "",
            "matricula": car.get("car_matricula") or "",
            "car_estat": car.get("car_estat"),
            "comandes": comandes,
            "totals": _totals(totes),
        })

    # Primer les que surten abans. Les que no tenen data/hora, al final.
    out.sort(key=lambda x: (x["data_sortida"] or "9999-99-99",
                            x["hora_sortida"] or "99:99", x["docentry"]))
    totes = [l for c in out for cm in c["comandes"] for l in cm["linies"]]
    return {"carregues": out, "totals": _totals(totes)}


def _lots_per_linia(dades: dict) -> dict[tuple[int, int], list[dict]]:
    """Els lots pistolejats de cada linia ({lot, kg, sacs, albara}), si el
    backend els ha llegit (`amb_lots`): primer els que ja tenen albara."""
    out: dict[tuple[int, int], list[dict]] = {}
    for p in dades.get("lots") or []:
        out.setdefault((int(p["comanda"]), int(p["linia"])), []).append(
            {"lot": p["lot"], "kg": round(float(p["kg"]), 3),
             "sacs": round(float(p["sacs"]), 2), "albara": bool(p["albara"])})
    for v in out.values():
        v.sort(key=lambda x: (not x["albara"], x["lot"]))
    return out


ESTAT_SENSE_DADES = "sense_dades"


def _acumula(acc: dict, l: dict, lc: dict, cancelat: dict | None = None) -> None:
    """Suma a `acc` una linia de comanda: `l` es la linia crua del backend i
    `lc` la que torna `_linia` (amb el pendent ja calculat). `cancelat`: les
    lectures d'albarans cancel·lats d'aquesta linia, si n'hi ha."""
    if cancelat:
        acc["kg_cancelat"] += cancelat["kg"]
        acc["albarans_cancelats"] |= cancelat["albarans"]
    kg = float(l.get("kg") or 0)
    sacs = float(l.get("sacs") or 0)
    kg_fets = max(kg - lc["kg_pendents"], 0.0)
    acc["kg_total"] += kg
    acc["kg_fets"] += kg_fets
    acc["kg_pistolejats"] += lc["kg_pistolejats"]
    if sacs > 0 and kg > 0 and not l.get("granel"):
        acc["sacs_total"] += sacs
        acc["sacs_fets"] += sacs * kg_fets / kg
    else:
        acc["sense_sacs"] = True


def _nou_acc() -> dict:
    return {"kg_total": 0.0, "kg_fets": 0.0, "kg_pistolejats": 0.0,
            "sacs_total": 0.0, "sacs_fets": 0.0, "sense_sacs": False,
            "kg_cancelat": 0.0, "albarans_cancelats": set()}


def _tanca(acc: dict | None) -> dict:
    if acc is None:
        return {"estat": ESTAT_SENSE_DADES, "kg_total": 0, "kg_fets": 0, "kg_pendents": 0,
                "sacs_total": None, "sacs_fets": None, "percent": 0, "cancelat": None}
    kg_pend = max(acc["kg_total"] - acc["kg_fets"], 0.0)
    if kg_pend <= _EPSILON:
        estat = ESTAT_COMPLET
    elif acc["kg_fets"] > _EPSILON or acc["kg_pistolejats"] > _EPSILON:
        estat = ESTAT_PARCIAL
    else:
        estat = ESTAT_PENDENT
    # Sacs nomes si totes les linies en tenen; si no, la suma enganyaria.
    amb_sacs = not acc["sense_sacs"] and acc["sacs_total"] > 0
    return {
        "estat": estat,
        "kg_total": round(acc["kg_total"], 3),
        "kg_fets": round(acc["kg_fets"], 3),
        "kg_pendents": round(kg_pend, 3),
        "sacs_total": round(acc["sacs_total"], 2) if amb_sacs else None,
        "sacs_fets": round(acc["sacs_fets"], 2) if amb_sacs else None,
        "percent": round(100 * acc["kg_fets"] / acc["kg_total"]) if acc["kg_total"] > _EPSILON else 100,
        # Lectures d'albarans cancel·lats: la mercaderia pot ser al palet.
        "cancelat": ({"kg": round(acc["kg_cancelat"], 3), "albarans": sorted(acc["albarans_cancelats"])}
                     if acc["kg_cancelat"] > _EPSILON else None),
    }


def progres_per_carrega(dades: dict) -> dict[int, dict]:
    """Progres del pistolejat de cada carrega sencera (pagina principal).

    `dades`: `obtenir_dades_pistolejat(ids, incloure_tancades=True)`. Les
    linies amb albara compten com a fetes, aixi que el % es sobre tota la
    carrega. Retorna {docentry_carrega: {estat, percent, kg_total, kg_fets,
    n_comandes, comandes_albara}} (`comandes_albara`: [{comanda, albarans}]
    amb el DocNum de cada comanda amb albara no cancel·lat i els DocNum dels
    seus albarans); les carregues sense cap linia no hi surten. El % no
    arriba a 100 mentre falti algun kg (l'arrodoniment no ho ha d'amagar).
    """
    pist = _suma_pistolejats(dades)
    albarans = _albarans_per_comanda(dades)
    accs: dict[int, dict] = {}
    comandes: dict[int, list] = {}
    for c in dades.get("comandes") or []:
        if c.get("linies"):
            comandes.setdefault(int(c["carrega"]), []).append(c)
        for l in c.get("linies") or []:
            clau = (int(c["docentry"]), int(l.get("linia") or 0))
            _acumula(accs.setdefault(int(c["carrega"]), _nou_acc()), l, _linia(l, pist.get(clau)))
    out: dict[int, dict] = {}
    for car, acc in accs.items():
        t = _tanca(acc)
        percent = 100 if t["estat"] == ESTAT_COMPLET else min(t["percent"], 99)
        cms = comandes.get(car, [])
        out[car] = {"estat": t["estat"], "percent": percent,
                    "kg_total": t["kg_total"], "kg_fets": t["kg_fets"],
                    "n_comandes": len(cms),
                    "comandes_albara": sorted(
                        ({"comanda": int(c.get("docnum") or 0), "albarans": albarans[int(c["docentry"])]}
                         for c in cms if albarans.get(int(c["docentry"]))),
                        key=lambda x: x["comanda"])}
    return out


def _docentry_carrega(carrega_id) -> int | None:
    """`SAP/{Series}/{DocEntry}` -> DocEntry."""
    try:
        return int(str(carrega_id).rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def progres_agrupacio(resultat: dict, dades: dict) -> dict:
    """Progres de cada producte d'una agrupacio segons el pistolejat.

    `resultat`: el `resultat` desat de l'agrupacio (`agregador.serialitzar`).
    `dades`: `obtenir_dades_pistolejat(carregues, incloure_tancades=True)`.

    Un producte esta fet quan, a totes les linies de comanda de les seves
    carregues, el que falta (`kg_oberts - pistolejat`) es zero: o s'ha
    pistolejat tot o ja hi ha albara. Es compara en kg; els sacs de
    l'agrupacio son els del motor d'embalatges i nomes es mostren.

    Un producte (o una carrega d'un producte) sense cap linia a SAP surt
    `sense_dades` i COMPTA com a fet: l'agrupacio es va fer a partir de les
    comandes, aixi que si ja no n'hi ha cap (comanda cancel·lada o moguda
    d'ordre de carrega) no queda res per carregar. Si no, l'agrupacio no
    s'acabaria mai sola.
    """
    pist = _suma_pistolejats(dades)
    canc = _suma_cancelats(dades)

    # (art_codi, docentry carrega) -> acumulat
    accs: dict[tuple[str, int], dict] = {}
    for c in dades.get("comandes") or []:
        car = int(c["carrega"])
        for l in c.get("linies") or []:
            clau = (int(c["docentry"]), int(l.get("linia") or 0))
            lc = _linia(l, pist.get(clau))
            _acumula(accs.setdefault((lc["art_codi"], car), _nou_acc()), l, lc, canc.get(clau))

    productes: dict[str, dict] = {}
    for p in resultat.get("productes") or []:
        art = p.get("art_codi") or ""
        total: dict | None = None
        per_carrega: dict[str, dict] = {}
        for pc in p.get("per_carrega") or []:
            acc = accs.get((art, _docentry_carrega(pc.get("carrega_id"))))
            per_carrega[str(pc.get("carrega_id"))] = _tanca(acc)
            if acc is not None:
                total = total or _nou_acc()
                for k in ("kg_total", "kg_fets", "kg_pistolejats", "sacs_total", "sacs_fets", "kg_cancelat"):
                    total[k] += acc[k]
                total["sense_sacs"] = total["sense_sacs"] or acc["sense_sacs"]
                total["albarans_cancelats"] |= acc["albarans_cancelats"]
        productes[art] = {**_tanca(total), "per_carrega": per_carrega}

    fets = sorted(a for a, v in productes.items()
                  if v["estat"] in (ESTAT_COMPLET, ESTAT_SENSE_DADES))
    kg_total = sum(v["kg_total"] for v in productes.values())
    kg_fets = sum(v["kg_fets"] for v in productes.values())
    percent = round(100 * kg_fets / kg_total) if kg_total > _EPSILON else 0
    if len(fets) < len(productes):
        # L'arrodoniment no pot dir 100% si encara falta algun producte.
        percent = min(percent, 99)
    elif productes:
        percent = 100
    return {
        "productes": productes,
        "fets": fets,
        "n_fets": len(fets),
        "n_productes": len(productes),
        "percent": percent,
    }
