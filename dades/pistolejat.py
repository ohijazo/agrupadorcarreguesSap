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
    # sense sacs (granel, unitats soltes amb PackQty 0) no en tenen.
    if sacs > 0 and kg > 0:
        sacs_oberts = round(kg_oberts * sacs / kg, 2)
        sacs_pend = round(max(sacs_oberts - sacs_pist, 0.0), 2)
    else:
        sacs_oberts = sacs_pend = None

    return {
        "linia": int(l.get("linia") or 0),
        "art_codi": l.get("art_codi") or "",
        "art_descrip": l.get("art_descrip") or "",
        "unitat": l.get("unitat") or "",
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

    Amb `nomes_pendents`, es treuen les linies completes, les comandes i
    carregues que queden buides, i les carregues ja sortides.
    """
    pist = _suma_pistolejats(dades)
    estats = dades.get("estats") or {}

    per_carrega: dict[int, list[dict]] = {}
    for c in dades.get("comandes") or []:
        linies = [_linia(l, pist.get((int(c["docentry"]), int(l.get("linia") or 0))))
                  for l in sorted(c.get("linies") or [], key=lambda x: int(x.get("linia") or 0))]
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


ESTAT_SENSE_DADES = "sense_dades"


def _acumula(acc: dict, l: dict, lc: dict) -> None:
    """Suma a `acc` una linia de comanda: `l` es la linia crua del backend i
    `lc` la que torna `_linia` (amb el pendent ja calculat)."""
    kg = float(l.get("kg") or 0)
    sacs = float(l.get("sacs") or 0)
    kg_fets = max(kg - lc["kg_pendents"], 0.0)
    acc["kg_total"] += kg
    acc["kg_fets"] += kg_fets
    acc["kg_pistolejats"] += lc["kg_pistolejats"]
    if sacs > 0 and kg > 0:
        acc["sacs_total"] += sacs
        acc["sacs_fets"] += sacs * kg_fets / kg
    else:
        acc["sense_sacs"] = True


def _nou_acc() -> dict:
    return {"kg_total": 0.0, "kg_fets": 0.0, "kg_pistolejats": 0.0,
            "sacs_total": 0.0, "sacs_fets": 0.0, "sense_sacs": False}


def _tanca(acc: dict | None) -> dict:
    if acc is None:
        return {"estat": ESTAT_SENSE_DADES, "kg_total": 0, "kg_fets": 0, "kg_pendents": 0,
                "sacs_total": None, "sacs_fets": None, "percent": 0}
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
    }


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

    # (art_codi, docentry carrega) -> acumulat
    accs: dict[tuple[str, int], dict] = {}
    for c in dades.get("comandes") or []:
        car = int(c["carrega"])
        for l in c.get("linies") or []:
            lc = _linia(l, pist.get((int(c["docentry"]), int(l.get("linia") or 0))))
            _acumula(accs.setdefault((lc["art_codi"], car), _nou_acc()), l, lc)

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
                for k in ("kg_total", "kg_fets", "kg_pistolejats", "sacs_total", "sacs_fets"):
                    total[k] += acc[k]
                total["sense_sacs"] = total["sense_sacs"] or acc["sense_sacs"]
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
