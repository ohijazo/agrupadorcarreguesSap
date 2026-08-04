"""
Compara les Ordres de Carrega Obertes visibles a SAP (captura del 2026-08-03)
amb el que retorna l'endpoint /api/carregues de l'app local.

Us: python scripts/verificar_ordres_obertes.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.parse

APP_URL = "http://127.0.0.1:5004"
DESDE = "2026-04-01"
FINS = "2026-08-01"

# Extret de la captura de SAP (finestra "Órdenes de Carga Abiertas")
# Actualitzat 2026-08-04 amb la llista completa (26 ordres).
ESPERATS = {
    1:  ("2026-04-24", "prova ordre de càrrega"),
    4:  ("2026-04-30", "xx"),
    6:  ("2026-05-06", ""),
    24: ("2026-06-09", "PROVA3"),
    22: ("2026-06-10", "TISA 24P"),
    23: ("2026-06-13", "OC LA FLECA"),
    32: ("2026-06-29", "MATAS 1 PROVA"),
    35: ("2026-07-05", ""),
    45: ("2026-07-17", "MATAS 1P SCS BCN"),
    25: ("2026-07-22", ""),
    37: ("2026-07-22", ""),
    38: ("2026-07-23", "prova prova 38"),
    49: ("2026-07-23", ""),
    46: ("2026-07-24", "ENSO PAL MALLORCA"),
    30: ("2026-07-30", ""),
    # Sense data de sortida informada a SAP:
    3:  ("", "s"),
    8:  ("", ""),
    19: ("", ""),
    20: ("", "prova Log 2"),
    27: ("", ""),
    29: ("", ""),
    36: ("", ""),
    41: ("", "xxxxxxxxxxxxxxxxxxxxxxxxxxxx41"),
    43: ("", ""),
    44: ("", "MATAS 14P SACS BCN"),
    48: ("", ""),
}


def fetch_carregues() -> list[dict]:
    qs = urllib.parse.urlencode({
        "desde": DESDE,
        "fins": FINS,
        "limit": 500,
        "offset": 0,
    })
    url = f"{APP_URL}/api/carregues?{qs}"
    print(f"GET {url}")
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    items = payload.get("items", [])
    print(f"Items rebuts: {len(items)} (total={payload.get('total')})")
    return items


def normalitza_data(v) -> str:
    if not v:
        return ""
    s = str(v)
    return s[:10]  # YYYY-MM-DD


def main() -> int:
    try:
        items = fetch_carregues()
    except Exception as exc:
        print(f"ERROR cridant l'API: {exc}", file=sys.stderr)
        return 2

    per_docnum: dict[int, dict] = {}
    for it in items:
        docnum = it.get("car_numero")
        if docnum in (None, ""):
            continue
        try:
            per_docnum[int(docnum)] = it
        except (TypeError, ValueError):
            continue

    print()
    print("=" * 70)
    print("COMPARACIO amb els 14 DocNum de la captura SAP")
    print("=" * 70)

    ok = 0
    diffs: list[str] = []
    faltants: list[int] = []

    for docnum, (data_esp, nom_esp) in sorted(ESPERATS.items()):
        it = per_docnum.get(docnum)
        if not it:
            faltants.append(docnum)
            print(f"FALTA  DocNum {docnum:>3}  esperat {data_esp}  '{nom_esp}'")
            continue
        data_app = normalitza_data(it.get("car_fecsalida"))
        nom_app = (it.get("car_descripcion") or "").strip()
        marca = "OK   "
        detalls: list[str] = []
        if data_app != data_esp:
            marca = "DIFF "
            detalls.append(f"data app={data_app}")
        if (nom_app or "") != (nom_esp or ""):
            marca = "DIFF "
            detalls.append(f"nom app='{nom_app}'")
        if marca == "OK   ":
            ok += 1
        else:
            diffs.append(f"{docnum}: {'; '.join(detalls)}")
        print(f"{marca}DocNum {docnum:>3}  {data_app}  '{nom_app}'"
              + (f"   [esperat {data_esp} '{nom_esp}']" if marca != "OK   " else ""))

    extres = sorted(set(per_docnum) - set(ESPERATS))
    print()
    print("-" * 70)
    print(f"Coincideixen: {ok}/{len(ESPERATS)}")
    if faltants:
        print(f"Faltants a l'app: {faltants}")
    if diffs:
        print(f"Diferents: {diffs}")
    print(f"Extres a l'app (no eren a la captura de SAP): {len(extres)}")
    for docnum in extres:
        it = per_docnum[docnum]
        d = normalitza_data(it.get("car_fecsalida"))
        n = (it.get("car_descripcion") or "").strip()
        print(f"  +{docnum:>3}  {d}  '{n}'")

    return 0 if (not faltants and not diffs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
