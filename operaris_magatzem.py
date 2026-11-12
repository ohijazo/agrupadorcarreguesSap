"""Operaris de magatzem que poden cancel·lar albarans a "Gestió d'albarans".

Cada cancel·lacio la signa un operari amb el seu codi (l'ID d'usuari del
departament Magatzem). El codi nomes serveix per identificar-lo: enlloc es
desa ni s'ensenya, nomes el nom.
"""
from __future__ import annotations

OPERARIS_CANCELACIO: dict[int, str] = {
    193: "Abdelkrim Fahchouch",
    218: "Adil Ennali",
    247: "Hamza Namousse",
    208: "Jhon Pablo Fernandez",
    127: "Joan Ballesteros Solbes",
    185: "Jose Gerardo Galo",
    175: "Juan Luís Piloto",
    248: "Leyan Valdes",
    226: "Oussama Aknaf",
}


def nom_operari(codi) -> str | None:
    """Nom de l'operari amb aquest codi, o None si no pot cancel·lar."""
    codi = str(codi if codi is not None else "").strip()
    if not codi.isdigit() or len(codi) > 6:
        return None
    return OPERARIS_CANCELACIO.get(int(codi))
