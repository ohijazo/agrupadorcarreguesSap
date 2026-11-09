from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CarregaResumen:
    carrega_id: str          # "2026/01/0001234"
    eje: str
    sca: str
    car: str
    tra_codi: str
    transportista: str       # nom (TRANS.tra_nom)
    data_sortida: Optional[str] = None
    matricula: str = ""
    conductor: str = ""
    observacions: str = ""
    descripcio: str = ""     # nom curt: "MATAS 14", "CARLES", ...


@dataclass
class PaletDetall:
    """Un palet físic dins una càrrega, amb el seu contingut d'un article concret."""
    tipus_palet: str          # art_codi del palet (01030, BasePalet, etc.)
    tipus_palet_descrip: str
    sacs: int                 # nombre de sacs d'aquest article en aquest palet
    sacs_x_base: int = 0      # sacs per capa/base del palet (com a l'app de comandes)
    max_sacs: int = 0         # capacitat màxima del palet
    comanda: str = ""         # "sal/cpa" — comanda d'origen (camp ERP: tipus 'A' o 'P')
    det_tipo: str = ""        # 'A' o 'P' al sistema ERP (intern; per a la UI són totes "comanda")


@dataclass
class CarregaPerProducte:
    """Desglossament d'embalatges d'un producte dins d'una càrrega concreta."""
    carrega_id: str
    transportista: str
    tra_codi: str
    total_sacs: int = 0
    total_kg: float = 0.0
    palets: list[PaletDetall] = field(default_factory=list)


@dataclass
class AgrupacioProducte:
    """Resultat agregat d'un producte a través de totes les càrregues seleccionades."""
    art_codi: str
    art_descrip: str
    tunitat: str = ""
    total_sacs: int = 0
    total_kg: float = 0.0
    per_carrega: list[CarregaPerProducte] = field(default_factory=list)


@dataclass
class Incidencia:
    carrega_id: str
    comanda: str              # "sal/cpa"
    tipus: str                # 'error' | 'warning'
    missatge: str


@dataclass
class TipusPaletPerCarrega:
    """Quants palets físics d'un tipus es preparen per a una càrrega concreta."""
    carrega_id: str
    quantitat: int


@dataclass
class TipusPaletRecompte:
    """Recompte de palets físics agrupats per tipus a tot el resultat."""
    tipus_palet: str
    tipus_palet_descrip: str
    quantitat: int
    per_carrega: list[TipusPaletPerCarrega] = field(default_factory=list)


@dataclass
class PaletFisic:
    """Un palet físic sencer (un embalatge no propi del motor), per a
    l'etiqueta de palet. Pot portar més d'un article."""
    carrega_id: str
    comanda: str              # "Series/DocNum"
    tipus_palet: str
    tipus_palet_descrip: str
    sacs: int                 # total de sacs del palet
    articles: list[tuple[str, str, int]] = field(default_factory=list)  # (art_codi, descrip, sacs)


@dataclass
class ResultatAgrupacio:
    carregues: list[CarregaResumen] = field(default_factory=list)
    productes: list[AgrupacioProducte] = field(default_factory=list)
    incidencies: list[Incidencia] = field(default_factory=list)
    total_palets_fisics: int = 0
    total_sacs: int = 0
    total_kg: float = 0.0
    tipus_palets: list[TipusPaletRecompte] = field(default_factory=list)
    # Palets físics un per un, en l'ordre de càrrega i comanda. Només per a
    # les etiquetes de palet: `serialitzar` no els desa amb l'agrupació.
    palets: list[PaletFisic] = field(default_factory=list)
