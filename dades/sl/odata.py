"""Construccio de literals i filtres OData per al Service Layer de SAP B1.

El Service Layer d'aquesta instal·lacio es **OData v3** (B1 10.0, versio
1000320), no v4. Aixo determina la sintaxi: `$inlinecount=allpages` en lloc de
`$count=true`, literals `datetime'...'`, i `substringof(cerca, camp)` en lloc
de `contains(camp, cerca)` — tot i que aquesta instal·lacio accepta tambe
algunes formes de v4.

Funcions que el Service Layer NO suporta i que per tant no s'han de generar
mai des d'aqui (provat: retornen `Query string error - Not supported function`):
`toupper`, `tolower`, `trim`, `length`, `indexof`, `year`. Tampoc accepta cap
funcio dins de `$orderby`. El que depengui d'aixo s'ha de fer en Python.
"""
from __future__ import annotations

from datetime import date, datetime

# Nombre de termes per cada cadena d'`or`. El Service Layer i els servidors
# web del cami tenen limits de llargada d'URL i de complexitat de $filter;
# trossejar evita topar-hi sense haver de calcular bytes exactes.
TERMES_PER_CRIDA = 40


def text(valor: str) -> str:
    """Literal de text OData. Les cometes simples s'escapen duplicant-les."""
    return "'" + str(valor).replace("'", "''") + "'"


def data_hora(valor: date | datetime) -> str:
    """Literal `datetime'...'` d'OData v3.

    Compte: les dates del Service Layer arriben amb un sufix `Z` que es fals
    (son dates locals sense zona), i els literals que hi enviem s'interpreten
    igual. No fem cap conversio de zona a proposit: fer-ne-hi desplacaria els
    resultats respecte del que retorna el SQL Server.
    """
    if isinstance(valor, datetime):
        return "datetime'" + valor.strftime("%Y-%m-%dT%H:%M:%S") + "'"
    return "datetime'" + valor.strftime("%Y-%m-%dT00:00:00") + "'"


def o(*condicions: str) -> str:
    """Uneix condicions amb `or`, cada una entre parentesis."""
    parts = [c for c in condicions if c]
    if not parts:
        return ""
    return " or ".join(f"({c})" for c in parts)


def i(*condicions: str) -> str:
    """Uneix condicions amb `and`, cada una entre parentesis."""
    parts = [c for c in condicions if c]
    if not parts:
        return ""
    return " and ".join(f"({c})" for c in parts)


def qualsevol_de(camp: str, valors) -> str:
    """`camp eq v1 or camp eq v2 or ...` per a una llista de valors de text."""
    return o(*[f"{camp} eq {text(v)}" for v in valors])


def qualsevol_num(camp: str, valors) -> str:
    """Igual que `qualsevol_de` pero per a valors numerics (sense cometes)."""
    return o(*[f"{camp} eq {int(v)}" for v in valors])


def trossos(valors, mida: int = TERMES_PER_CRIDA):
    """Parteix una llista en trossos per generar diverses crides."""
    valors = list(valors)
    for n in range(0, len(valors), mida):
        yield valors[n:n + mida]


def finestra_coalesce(camp: str, camp_alt: str, desde, fins) -> str:
    """Equivalent exacte de `COALESCE(camp, camp_alt) >= desde AND < fins`.

    El Service Layer no te `coalesce`, pero la condicio es pot expressar com
    l'OR de dues branques disjuntes que cobreixen tot l'espai: o el camp
    principal te valor i s'hi compara, o es nul i es compara l'alternatiu.
    Per construccio dona el mateix conjunt que el COALESCE del SQL.

    `fins` es EXCLUSIU, igual que al SQL (`fins + 1 dia` amb `<`).
    """
    amb = i(f"{camp} ne null",
            f"{camp} ge {data_hora(desde)}",
            f"{camp} lt {data_hora(fins)}")
    sense = i(f"{camp} eq null",
              f"{camp_alt} ge {data_hora(desde)}",
              f"{camp_alt} lt {data_hora(fins)}")
    return o(amb, sense)
