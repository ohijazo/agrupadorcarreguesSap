-- Agregats per carrega, precalculats a partir de les comandes de SAP.
-- Idempotent (IF NOT EXISTS): es pot aplicar sense risc sobre una BD ja migrada.
--
-- PER QUE EXISTEIX AQUESTA TAULA
--
-- El llistat de carregues necessita quatre camps derivats de les linies de
-- comanda: kg_total, num_comandes, palletitzable i is_granel. Amb SQL directe
-- surten de cinc subconsultes correlacionades sobre ORDR + RDR1 + OITM.
--
-- El Service Layer de SAP B1 no pot fer-ho: no te cap JOIN (0 navigation
-- properties en 436 entitats) i no permet agregar ni filtrar sobre linies de
-- document (`aggregate(DocumentLines/Quantity with sum as kg)` respon
-- `invalid entity 'DocumentLines'`). L'unica manera de tenir aquests camps es
-- portar-se les linies senceres i agregar-les fora de SAP, i aixo no es pot
-- fer a cada peticio: les linies no es poden retallar amb $select
-- (`Invalid navigation property:DocumentLines`), venen amb 247 camps i pesen
-- ~19 KB per comanda. Una pagina de llistat son 500 carregues, i el frontend
-- en demana 1000 al calendari i refresca cada 5 s.
--
-- Per aixo es precalculen aqui, amb un refrescador periodic
-- (scripts/refrescar_agregats.py). El preu es que el llistat passa a ser
-- eventualment consistent; la fitxa de detall segueix llegint en viu.
--
-- UNA FILA PER COMANDA, NO PER CARREGA
--
-- Decisio deliberada. Fa que l'agregat per carrega sigui un GROUP BY, que el
-- filtre per article sigui un index GIN, i que el refresc incremental pugui
-- anar per comanda. I sobretot: permet detectar que una comanda ha canviat de
-- carrega, cosa que amb files per carrega passaria desapercebuda i deixaria
-- la carrega d'origen amb un agregat massa alt per sempre.

CREATE TABLE IF NOT EXISTS ordre_carrega_cache (
    -- DocEntry de la comanda (ORDR). Clau natural.
    order_docentry    INTEGER      PRIMARY KEY,
    -- DocEntry de la carrega a la qual pertany (ORDR.U_SEIOrdCargId).
    carrega_docentry  INTEGER      NOT NULL,
    -- SUM(RDR1.Quantity) de totes les linies. L'app interpreta Quantity com
    -- a kg. ATENCIO: compta TOTES les linies, tambe les que no tenen article
    -- al mestre, perque el SQL original no fa cap JOIN amb OITM per calcular
    -- kg_total.
    kg                NUMERIC      NOT NULL DEFAULT 0,
    -- Hi ha alguna linia amb unitats > 0 i unitat de venda fora de
    -- ('UNI','GRA'). A diferencia de kg, aqui el SQL original fa un JOIN
    -- INNER amb OITM: una linia amb un article que no es al mestre NO compta.
    te_palletitzable  BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Hi ha alguna linia amb unitat de venda 'GRA' i Quantity > 0.
    te_granel         BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Articles de les linies, per al filtre per article del llistat. Amb
    -- l'index GIN, el filtre afecta correctament tambe el comptador total,
    -- que es el que fa avui el EXISTS del SQL.
    item_codes        TEXT[]       NOT NULL DEFAULT '{}',
    refrescat_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ordre_carrega_cache_carrega
    ON ordre_carrega_cache (carrega_docentry);

CREATE INDEX IF NOT EXISTS idx_ordre_carrega_cache_items
    ON ordre_carrega_cache USING GIN (item_codes);

-- ---------------------------------------------------------------------------
-- Estat del refrescador. Una sola fila.
--
-- L'antiguitat d'aqui la mira /health i la torna com a 503 si se passa del
-- llindar: un agregat encallat en silenci es la pitjor fallada possible
-- d'aquest disseny, perque el llistat segueix responent amb dades velles i
-- ningu se n'adona.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agregats_meta (
    id                     SMALLINT     PRIMARY KEY CHECK (id = 1),
    ultim_refresc_complet  TIMESTAMPTZ,
    ultim_refresc_incr     TIMESTAMPTZ,
    ultim_error            TEXT,
    comandes               INTEGER      NOT NULL DEFAULT 0
);

INSERT INTO agregats_meta (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
