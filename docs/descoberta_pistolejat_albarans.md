# Descoberta: pistolejat i albarans de magatzem (SAP B1, DB_FARIN_TEST)

Resultat de `scripts/discover_udt_pistolejat.py` (només lectura), 28-10-2026.
Validat amb el consultor SEIDOR el 29-10-2026 (vegeu "Respostes de SEIDOR" al final).

## 1. El pistolejat: `@SEIOPIC` ("Artículos recogidos")

Cada fila és **un pistolejat d'una línia de comanda, amb lot**. La taula té 29 files a TEST.

| Camp | Significat (deduït) | Exemple |
|---|---|---|
| `U_DocEntry` | Ordre de càrrega (`@SEI_ORDENCARGA`, = `ORDR.U_SEIOrdCargId`) | 98 |
| `U_BaseObject` / `U_BaseEntry` / `U_BaseLine` | Línia de comanda d'origen (17 = comanda de venda) | 17 / 330 / 0 |
| `U_ItemCode`, `U_WhsCode`, `U_BinAbs` | Article, magatzem, ubicació | 33851, 01 |
| `U_MdAbsEntry` | Lot (`OBTN.AbsEntry`) | 3254 → lot 26010320 |
| `U_Quantity` | Quantitat en unitat de venda (sacs, palets...) | 10 |
| `U_InvQty` | Quantitat en unitat d'inventari | 250 |
| `U_TargetType` / `U_TargetEntry` | Document generat: 15 = albarà, 67 = trasllat. **Buit = pistolejat però encara sense albarà** | 15 / 148 |

Exemple quadrat: comanda 330 (ordre de càrrega 98), línia 0, article 33851, `Quantity` = 500.
Té dos pistolejats de 250 kg cadascun (lots 3245 i 3254) i l'SGA en va crear l'albarà 148.

### Proposta de càlcul de "pendent de pistolejar"
Per a cada línia oberta (`RDR1.LineStatus='O'`) de les comandes d'una ordre de càrrega:

```
pendent = RDR1.OpenInvQty − Σ @SEIOPIC.U_InvQty
          (mateix BaseEntry/BaseLine, U_TargetEntry buit)
```

Es compara en **unitat d'inventari** (`InvQty`), perquè `U_Quantity` va en unitat de venda.
Estat de la línia: pendent (0 pistolejat), parcial o complet.

## 2. Estats de comanda: `@SEIESTATSCOM`

És un log d'estats per comanda (`U_SEIDocEntry` = `ORDR.DocEntry`), amb data i hora.

| Estat | Acció que el genera |
|---|---|
| PENDENT | Alta comanda |
| CONFIRMADA | Alta/modificació comanda, **Cancel·lar albarà** |
| PREPARADA | Creació albarà |
| SORTIDA | En sortida |
| FACTURADA | Creació factura |

Ja existeix un procés SEIDOR que, en cancel·lar un albarà, torna la comanda a CONFIRMADA.
Serveix per al dashboard: l'últim estat de cada comanda diu si està pendent de preparar o ja preparada.

## 3. Albarans de magatzem

- Tots els albarans van per la mateixa sèrie (266), així que **la sèrie no serveix per distingir-los**.
- Els crea l'**usuari SGA**: `SGA1` (USERID 22) i `SGA2` (USERID 23), via `ODLN.UserSign`. Proposta de criteri: `ALBARANS_MAGATZEM_USUARIS=SGA1,SGA2`.
- Porten `U_SEIOrdCargId`, així que es poden mostrar agrupats per càrrega.
- Cancel·lables: `DocStatus='O'`, `CANCELED='N'` i sense factura (cap `DLN1.TargetType=13`).

## Preguntes per al consultor SEIDOR

1. És correcta la lectura de `@SEIOPIC`, en particular que `U_DocEntry` és l'ordre de càrrega i que `U_TargetEntry` buit vol dir "pistolejat sense albarà"?
2. Quan es cancel·la un albarà de l'SGA, què passa amb les files de `@SEIOPIC`?
   - A la comanda 279 hi ha una fila amb target = albarà 99 (cancel·lat) i una altra sense target.
   - Cal que les esborri o reobri alguna cosa?
   - Ho fa el `TransactionNotification` (i per tant també funcionaria si cancel·lem pel Service Layer)?
3. Està bé cancel·lar amb `POST DeliveryNotes(n)/Cancel` des del Service Layer, o l'SGA espera un altre circuit?
4. L'addon genera alguna etiqueta de palet (`@SEICRETI` "Etiquetas" o un Crystal de B1Print) que hàgim de reutilitzar?

## Respostes de SEIDOR (29-10-2026)

**`@SEIOPIC`.** La lectura de dalt és correcta. Detalls que no sabíem:
- `Code` és autoincremental. `Name` és només informatiu, amb el format
  `ordre de càrrega # tipus base # DocEntry base # comptador`.
- `U_BaseObject` pot ser `17` (comanda de venda, `RDR1`) o `1250000001` (sol·licitud
  de trasllat, `WTQ1`). Per a les sol·licituds de trasllat, `U_WhsCode` és el magatzem
  d'origen i `U_WhsCodeTo` el de destí. L'app només mira les comandes (`17`).
- `U_ManagedBy` val `10000044` si l'article va per lots (`OBTN`), `10000045` si va
  per números de sèrie (`OSRN`) i NULL si no va per cap dels dos. `U_MdAbsEntry` és
  l'`AbsEntry` del lot o del número de sèrie.
- `U_Quantity` són els sacs que entra l'usuari a l'SGA. `U_InvQty` és la quantitat
  calculada.
- `U_BinAbs` és la ubicació (`OBIN`). Ara no es fa servir: no hi ha magatzems amb
  ubicacions.
- `U_TargetType`/`U_TargetEntry` plens vol dir que s'ha premut "Crear" a l'SGA.
  Aquestes línies ja no surten a "Detalle documento". Les que els tenen a NULL
  són les pendents.

**És un històric.** Les files només s'esborren quan l'usuari elimina línies a
"Detalle documento" de l'SGA. Quan es crea l'albarà no s'esborren.

**Si es cancel·la un albarà:**
- l'SGA deixa tornar a preparar la comanda;
- les files de l'albarà anterior es queden a la taula, apuntant-hi;
- per saber si està cancel·lat cal mirar `ODLN.CANCELED = 'Y'`.

Ho vam comprovar cancel·lant l'albarà 148 pel Service Layer des de l'app: es
comporta igual que des del client SAP, i el TransactionNotification també torna
la comanda a CONFIRMADA. Per tant:
- **pendents de pistolejar:** el càlcul (només files amb `U_TargetEntry` NULL) és
  correcte tal com està;
- **cancel·lació des de l'app:** no ha de tocar `@SEIOPIC`.
