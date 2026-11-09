"""Lògica d'agrupació de càrregues.

Per a cada càrrega seleccionada:
  1. Llegeix les comandes (Detcargas).
  2. Per a cada comanda, crida motor.calcular_embalatges() de l'app germana.
  3. Acumula els embalatges per (art_codi, transportista).

El motor s'importa via sys.path injectat a app.py.
"""
from collections import defaultdict
from typing import Any, Iterable

from consultes_carregues import obtenir_comandes_carrega, obtenir_descrip_articles
from models_agrupacio import (
    AgrupacioProducte, CarregaPerProducte, CarregaResumen,
    Incidencia, PaletDetall, PaletFisic, ResultatAgrupacio, TipusPaletRecompte,
    TipusPaletPerCarrega,
)


def _pes_per_tunitat(tunitat: str) -> float:
    """S25 -> 25, S10 -> 10, etc. GRA/UNI -> 0."""
    if tunitat and tunitat.startswith("S"):
        try:
            return float(tunitat[1:])
        except ValueError:
            return 0.0
    return 0.0


def agrupar(carregues_sel: list[dict]) -> ResultatAgrupacio:
    """Agrupa N càrregues en un únic resultat consolidat per producte.

    carregues_sel: llista de dicts amb keys
        eje_ejercicio, sca_serie, car_numero, transportista, tra_codi,
        carrega_id, car_fecsalida, car_matricula, car_nomconductor, car_observaciones.
    """
    # Import diferit: motor de l'app germana, ja al sys.path quan arribem aquí.
    from motor import calcular_embalatges  # type: ignore
    from models import Estat  # type: ignore  # noqa: F401

    resultat = ResultatAgrupacio()

    # Cache de comandes (eje, sal, cpa, tra, data) per evitar recalcular si surt 2 cops.
    cache_comanda: dict[tuple[str, str, str, str, str], Any] = {}

    # Estructura intermèdia: (art_codi) -> {
    #     "descrip", "tunitat",
    #     "per_carrega": (carrega_id) -> CarregaPerProducte
    # }
    acum: dict[str, dict] = {}

    palets_fisics_totals = 0
    palets_per_tipus: dict[str, dict] = {}

    for c in carregues_sel:
        resultat.carregues.append(CarregaResumen(
            carrega_id=c["carrega_id"],
            eje=c["eje_ejercicio"],
            sca=c["sca_serie"],
            car=c["car_numero"],
            tra_codi=c.get("tra_codi", ""),
            transportista=c.get("transportista", ""),
            data_sortida=c.get("car_fecsalida"),
            matricula=c.get("car_matricula", ""),
            conductor=c.get("car_nomconductor", ""),
            observacions=c.get("car_observaciones", ""),
            descripcio=c.get("car_descripcion", ""),
        ))

        comandes = obtenir_comandes_carrega(
            c["eje_ejercicio"], c["sca_serie"], c["car_numero"]
        )
        if not comandes:
            resultat.incidencies.append(Incidencia(
                carrega_id=c["carrega_id"],
                comanda="-",
                tipus="warning",
                missatge="La càrrega no té comandes a Detcargas.",
            ))
            continue

        # Data de referència de la càrrega per discriminar entre dos pending
        # amb mateix tra_codi (cassos URBAN, RYMOT, BOIX COMAS): preferim
        # car_fecllegada (data d'arribada al destí), després car_fecsalida.
        # Tipus: string "YYYY-MM-DD" — `consultes_carregues.py:349-353` serialitza
        # les dates amb strftime abans de retornar-les al payload.
        data_carrega: str | None = c.get("car_fecllegada") or c.get("car_fecsalida") or c.get("car_fecha")

        for a in comandes:
            tra_codi = c.get("tra_codi", "") or ""
            # `tra_codi` i `data_carrega` formen part de la clau de cache:
            # cargues amb tra/data diferents poden resoldre el mateix (eje,
            # sal, alb) a albarans diferents (cas 0004487: 0002389 → FORN CAP
            # VILA per data 25/06, 0002423 → URBAN SPICES per data 29/06).
            key = (a["eje_ejercicio"], a["sal_codigo"], a["cpa_albara"], tra_codi, data_carrega or "")
            try:
                if key in cache_comanda:
                    res = cache_comanda[key]
                else:
                    res = calcular_embalatges(
                        a["sal_codigo"], a["cpa_albara"],
                        tra_codi_carrega=tra_codi,
                        eje_ejercicio=a["eje_ejercicio"],
                        data_carrega=data_carrega,
                    )
                    cache_comanda[key] = res
            except (TypeError, AttributeError, NameError, ImportError):
                # Bugs de codi (no de dades): no els ofeguem com a incidència
                # silenciosa. Que l'endpoint torni 500 perquè es vegi al log
                # immediatament (cas 28/06/2026 amb data_carrega.isoformat()).
                raise
            except Exception as e:
                resultat.incidencies.append(Incidencia(
                    carrega_id=c["carrega_id"],
                    comanda=f"{a['sal_codigo']}/{a['cpa_albara']}",
                    tipus="error",
                    missatge=f"Error calculant: {e}",
                ))
                continue

            # Defensiu: si el motor retorna None (no només excepció) registrem
            # la incidència i continuem amb la següent comanda sense petar.
            if res is None or not getattr(res, "embalatges", None):
                estat_str = "-"
                if res is not None:
                    estat_attr = getattr(res, "estat", None)
                    estat_str = estat_attr.value if hasattr(estat_attr, "value") else str(estat_attr)  # type: ignore[union-attr]
                resultat.incidencies.append(Incidencia(
                    carrega_id=c["carrega_id"],
                    comanda=f"{a['sal_codigo']}/{a['cpa_albara']}",
                    tipus="warning",
                    missatge=f"Sense embalatges calculables (estat: {estat_str}).",
                ))
                continue

            # Mapa art_codi -> descripció / tunitat / pes_per_sac des de línies
            info_articles: dict[str, dict] = {}
            for l in res.linies:
                info_articles[l.art_codi] = {
                    "descrip": l.art_descrip,
                    "tunitat": l.tunitat,
                    "pes_sac": _pes_per_tunitat(l.tunitat),
                }

            # Descripcions de tipus_palet — surten de PaletResum
            descrip_palet: dict[str, str] = {
                p.art_codi: p.art_descrip for p in res.palets
            }

            # Recórrer embalatges: cada embalatge té un tipus_palet i una llista de contingut.
            for emb in res.embalatges:
                tipus = emb.tipus_palet or "?"
                tipus_descrip = descrip_palet.get(tipus, tipus)
                if not emb.es_embalatge_propi:
                    palets_fisics_totals += 1
                    bucket_pt = palets_per_tipus.setdefault(
                        tipus, {"descrip": tipus_descrip, "n": 0, "per_carrega": {}}
                    )
                    bucket_pt["n"] += 1
                    bucket_pt["per_carrega"][c["carrega_id"]] = \
                        bucket_pt["per_carrega"].get(c["carrega_id"], 0) + 1
                    if not bucket_pt["descrip"]:
                        bucket_pt["descrip"] = tipus_descrip

                palet = None
                if not emb.es_embalatge_propi:
                    palet = PaletFisic(
                        carrega_id=c["carrega_id"],
                        comanda=f"{a['sal_codigo']}/{a['cpa_albara']}",
                        tipus_palet=tipus,
                        tipus_palet_descrip=tipus_descrip,
                        sacs=0,
                    )
                for cont in emb.contingut:
                    art = cont.art_codi
                    sacs = int(cont.sacs)
                    if sacs <= 0:
                        continue
                    if palet is not None:
                        palet.sacs += sacs
                        palet.articles.append((art, info_articles.get(art, {}).get("descrip", cont.art_descrip), sacs))
                    info = info_articles.get(art, {})
                    descrip = info.get("descrip", cont.art_descrip)
                    tunitat = info.get("tunitat", "")
                    pes_sac = info.get("pes_sac", 0.0)
                    kg = sacs * pes_sac

                    bucket = acum.setdefault(art, {
                        "descrip": descrip,
                        "tunitat": tunitat,
                        "per_carrega": {},
                    })
                    cpc = bucket["per_carrega"].setdefault(
                        c["carrega_id"],
                        CarregaPerProducte(
                            carrega_id=c["carrega_id"],
                            transportista=c.get("transportista", ""),
                            tra_codi=c.get("tra_codi", ""),
                        ),
                    )
                    cpc.total_sacs += sacs
                    cpc.total_kg += kg
                    # Base efectiva: si l'article té base pròpia (RF11 + cantidadapilable),
                    # preval; altrament la base del palet (com mostra l'app germana).
                    base_efectiva = int(cont.sacs_x_base) if cont.sacs_x_base else int(emb.sacs_x_base or 0)
                    cpc.palets.append(PaletDetall(
                        tipus_palet=tipus,
                        tipus_palet_descrip=tipus_descrip,
                        sacs=sacs,
                        sacs_x_base=base_efectiva,
                        max_sacs=int(emb.max_sacs or 0),
                        comanda=f"{a['sal_codigo']}/{a['cpa_albara']}",
                        det_tipo=a.get("det_tipo", ""),
                    ))
                if palet is not None and palet.sacs > 0:
                    resultat.palets.append(palet)

    # Construir AgrupacioProducte finals
    for art_codi, bucket in sorted(acum.items()):
        per_carrega = list(bucket["per_carrega"].values())
        total_sacs = sum(x.total_sacs for x in per_carrega)
        total_kg   = sum(x.total_kg   for x in per_carrega)
        resultat.productes.append(AgrupacioProducte(
            art_codi=art_codi,
            art_descrip=bucket["descrip"],
            tunitat=bucket["tunitat"],
            total_sacs=total_sacs,
            total_kg=total_kg,
            per_carrega=per_carrega,
        ))
        resultat.total_sacs += total_sacs
        resultat.total_kg   += total_kg

    resultat.total_palets_fisics = palets_fisics_totals
    carrega_idx = {c.carrega_id: i for i, c in enumerate(resultat.carregues)}

    # Enriquim el descrip dels palets amb el text complet d'ARTICLES.
    # El motor germà retorna sovint una versió escurçada (sense mides), però
    # per imprimir-ho a paper volem "PALET PLASTIC EUROPEU 120X80" sencer.
    try:
        descrips_complets = obtenir_descrip_articles(list(palets_per_tipus.keys()))
    except Exception:
        # Si la BD no és accessible no bloquegem el resultat; ens quedem amb el descrip del motor
        descrips_complets = {}

    resultat.tipus_palets = [
        TipusPaletRecompte(
            tipus_palet=tipus,
            tipus_palet_descrip=descrips_complets.get(tipus) or info["descrip"] or tipus,
            quantitat=info["n"],
            per_carrega=[
                TipusPaletPerCarrega(carrega_id=cid, quantitat=q)
                for cid, q in sorted(
                    info["per_carrega"].items(),
                    key=lambda kv: carrega_idx.get(kv[0], 9999),
                )
            ],
        )
        for tipus, info in sorted(
            palets_per_tipus.items(), key=lambda kv: (-kv[1]["n"], kv[0])
        )
    ]
    return resultat


def serialitzar(r: ResultatAgrupacio) -> dict:
    return {
        "carregues": [vars(c) for c in r.carregues],
        "productes": [
            {
                "art_codi": p.art_codi,
                "art_descrip": p.art_descrip,
                "tunitat": p.tunitat,
                "total_sacs": p.total_sacs,
                "total_kg": round(p.total_kg, 2),
                "per_carrega": [
                    {
                        "carrega_id": pc.carrega_id,
                        "transportista": pc.transportista,
                        "tra_codi": pc.tra_codi,
                        "total_sacs": pc.total_sacs,
                        "total_kg": round(pc.total_kg, 2),
                        "palets": [vars(pd) for pd in pc.palets],
                    }
                    for pc in p.per_carrega
                ],
            }
            for p in r.productes
        ],
        "incidencies": [vars(i) for i in r.incidencies],
        "total_palets_fisics": r.total_palets_fisics,
        "total_sacs": r.total_sacs,
        "total_kg": round(r.total_kg, 2),
        "tipus_palets": [
            {
                "tipus_palet": t.tipus_palet,
                "tipus_palet_descrip": t.tipus_palet_descrip,
                "quantitat": t.quantitat,
                "per_carrega": [vars(pc) for pc in t.per_carrega],
            }
            for t in r.tipus_palets
        ],
    }
