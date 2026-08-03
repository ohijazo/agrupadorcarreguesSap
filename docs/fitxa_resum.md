# Agrupador de Càrregues

**URL:** http://agrupacions.agrienergia.local/ · **Estat:** en producció · **Període dev:** 2026 (38 h acumulades)

---

## Descripció

Aplicació web interna que automatitza la consolidació d'embalatges de múltiples càrregues de transport en un únic resum per producte. L'oficina filtra càrregues per data, transportista i article, les selecciona i obté instantàniament el càlcul de palets a preparar. Incorpora un **calendari digital** (la "pissarra digital") amb les càrregues del dia actualitzades al moment, consultable per tothom des de l'aplicació. Oficina i magatzem comparteixen el progrés en temps real.

## Necessitat

Abans, el responsable de magatzem treballava amb l'**Agrupador de Kais**, que oferia molta menys informació; havia de creuar dades manualment i perdia ~1 h/dia. Paral·lelament, l'oficina apuntava totes les càrregues a una **pissarra física**: una persona perdia temps escrivint-les i actualitzant-les, i la resta de l'equip havia d'acostar-se físicament cada vegada que volia consultar-les.
## Recursos dedicats

| Concepte | Valor |
|---|---|
| Hores de desenvolupament | **38 h** |
| Cost intern estimat (a 33,5 €/h cost empresa) | **1.273 €** |
| Stack tècnic | Python 3 · Flask · PostgreSQL 17 · SQL Server (lectura ERP) · Vanilla JS · Apache + Gunicorn |

## Retorn

### Quantitatiu (1 h/dia responsable magatzem + 45 min/dia oficina, 220 dies/any)

| Indicador | Valor anual |
|---|---|
| Hores alliberades | **~385–440 h/any** (48–55 jornades de 8 h) |
| Valoració orientativa (operari 20 €/h + oficina 25 €/h) | **≈ 9.900 €/any** |
| **Payback de la inversió** | **~1,5 mesos** |

L'estalvi del magatzem ve de **disposar de més informació en un sol lloc** que amb l'Agrupador de Kais. L'estalvi de l'oficina ve d'**eliminar la pissarra física**: ningú ha d'escriure-hi ni desplaçar-se a consultar-la.

### Qualitatiu

- **Pissarra digital** consultable des de qualsevol lloc; substitueix la pissarra física.
- **Zero duplicats:** validació automàtica que bloqueja una càrrega a dues agrupacions.
- **Procés estandarditzat i traçable** (qui-què-quan registrat sense esforç).
- **Dades digitals** per a futurs anàlisis de tendències (impossible amb Excel).

## Veredicte

**Inversió de 1.273 € → retorn de ~9.900 €/any.** ROI clarament positiu en tots els escenaris; fins i tot −75 % de l'estimació segueix alliberant 14 jornades/any.
