"""Etiquetes de palet: una per cada palet físic que calcula el motor.

Substitueix l'etiqueta que el magatzem feia amb Word: logo, DESTÍ en gran,
CLIENT (nom i carrer d'entrega), Nº CLIENT (posició del client dins la
càrrega; només el fan servir per a alguns destins), TRANSPORT i Nº SACS.

- Els palets surten de `agregador.agrupar` (`ResultatAgrupacio.palets`): un
  per embalatge no propi, amb la comanda i el total de sacs.
- El client i l'adreça d'entrega surten de la comanda
  (`obtenir_adreces_comandes`). La població es proposa com a destí.
- SAP no guarda l'ordre de descàrrega: el Nº client es proposa 1..N segons
  l'ordre dels clients dins la càrrega, i a la pantalla es pot canviar o
  deixar en blanc (aleshores no s'imprimeix).
"""
from __future__ import annotations

from models_agrupacio import ResultatAgrupacio


def _docnum(comanda: str) -> int | None:
    """"Series/DocNum" -> DocNum."""
    try:
        return int(str(comanda).rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def _num_carrega(carrega_id: str) -> str:
    """"SAP/{Series}/{DocEntry}" -> "97"."""
    ultim = str(carrega_id or "").rsplit("/", 1)[-1]
    return ultim.lstrip("0") or ultim


def construir(resultat: ResultatAgrupacio, adreces: dict[str, dict]) -> dict:
    """{clients: [...], etiquetes: [...], incidencies: [...]}.

    Un "client" és un client amb una adreça dins una càrrega (si té dues
    comandes a la mateixa càrrega i adreça, comparteixen destí i Nº client).
    Cada etiqueta apunta al seu client per `clau`.
    """
    carregues = {c.carrega_id: c for c in resultat.carregues}
    ordre_carrega = {c.carrega_id: i for i, c in enumerate(resultat.carregues)}

    clients: dict[str, dict] = {}
    etiquetes: list[dict] = []
    n_client_per_carrega: dict[str, int] = {}
    for p in sorted(resultat.palets, key=lambda p: (ordre_carrega.get(p.carrega_id, 999),
                                                    _docnum(p.comanda) or 0)):
        adr = adreces.get(p.comanda) or {}
        clau = f"{p.carrega_id}|{adr.get('cli_codi') or p.comanda}|{adr.get('carrer', '')}"
        cli = clients.get(clau)
        if cli is None:
            n = n_client_per_carrega.get(p.carrega_id, 0) + 1
            n_client_per_carrega[p.carrega_id] = n
            car = carregues.get(p.carrega_id)
            cli = clients[clau] = {
                "clau": clau,
                "carrega_id": p.carrega_id,
                "carrega_num": _num_carrega(p.carrega_id),
                "carrega_nom": (car.descripcio if car else "") or "",
                "transportista": (car.transportista if car else "") or "",
                "comandes": [],
                "cli_codi": adr.get("cli_codi", ""),
                "cli_nom": adr.get("cli_nom") or f"Comanda {p.comanda}",
                "carrer": adr.get("carrer", ""),
                "poblacio": adr.get("poblacio", ""),
                "n_client": n,
                "n_palets": 0,
            }
        if p.comanda not in cli["comandes"]:
            cli["comandes"].append(p.comanda)
        cli["n_palets"] += 1
        etiquetes.append({
            "clau": clau,
            "palet_n": cli["n_palets"],
            "sacs": p.sacs,
            "tipus_palet": p.tipus_palet_descrip or p.tipus_palet,
            "articles": [{"art_codi": a, "art_descrip": d, "sacs": s} for a, d, s in p.articles],
        })

    return {
        "clients": list(clients.values()),
        "etiquetes": etiquetes,
        "incidencies": [vars(i) for i in resultat.incidencies],
    }


def etiquetes_de(resultat: ResultatAgrupacio) -> dict:
    """Llegeix les adreces de les comandes dels palets i munta les etiquetes."""
    # Import aquí: importar la capa de dades carrega el .env (vegeu tests/conftest.py).
    from consultes_carregues import obtenir_adreces_comandes
    docnums = [n for n in (_docnum(p.comanda) for p in resultat.palets) if n is not None]
    return construir(resultat, obtenir_adreces_comandes(docnums))
