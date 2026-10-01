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
import unicodedata
from datetime import datetime

from dades.sl import odata as q
from dades.sl.client import client
from dades.sql.carregues import _estat_char_to_int

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
    return q.o(
        q.i("U_SEIDataS ne null", f"U_SEIDataS ge {q.data_hora(desde)}"),
        q.i("U_SEIDataS eq null", f"CreateDate ge {q.data_hora(desde)}"),
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
