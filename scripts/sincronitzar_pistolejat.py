"""Desa a `productes_preparats` el que l'SGA ja ha pistolejat (o ja te albara)
de les agrupacions vives, encara que ningu no tingui la preparacio oberta.

Us:
    python scripts/sincronitzar_pistolejat.py            # agrupacions dels ultims 30 dies
    python scripts/sincronitzar_pistolejat.py --dies 7

Al servidor va amb un timer de systemd cada 2 minuts. Fa una sola consulta a
SAP per a totes les carregues i nomes escriu quan hi ha canvis. Vegeu
preparacio_sga.py.
"""
import argparse
import logging
import os
import sys

# `import app` primer: carrega el .env i posa PREPARACIO_PATH al sys.path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import app  # noqa: F401,E402

import preparacio_sga  # noqa: E402

log = logging.getLogger("agrupacio")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dies", type=int,
                   default=int(os.environ.get("SINCRO_PISTOLEJAT_DIES", "30")),
                   help="Agrupacions creades fa menys d'aquests dies (per defecte 30).")
    args = p.parse_args()
    try:
        r = preparacio_sga.sincronitza_totes(args.dies)
    except Exception as e:
        log.exception("sincronitzacio del pistolejat fallida")
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"OK - {r['agrupacions']} agrupacions, {r['canviades']} amb canvis")
    return 0


if __name__ == "__main__":
    sys.exit(main())
