-- Esquema d'agrupacioCarregues a PostgreSQL.
-- Compatible amb PostgreSQL 12 o superior.
--
-- Ús al setup:
--   psql -h <host> -U <admin> -d <db> -f schema.sql

-- ---------------------------------------------------------------------------
-- Taula principal: una fila per agrupació desada
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agrupacions (
    id                    UUID         PRIMARY KEY,
    nom                   TEXT         NOT NULL,
    ts                    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    plantilla             BOOLEAN      NOT NULL DEFAULT FALSE,
    -- Camps resum precalculats per a llistats ràpids (sense parsejar JSONB)
    n_carregues           INTEGER      NOT NULL DEFAULT 0,
    n_productes           INTEGER      NOT NULL DEFAULT 0,
    total_palets_fisics   INTEGER      NOT NULL DEFAULT 0,
    total_sacs            INTEGER      NOT NULL DEFAULT 0,
    -- Cossos grans com a JSONB (input + resultat motor)
    carregues             JSONB        NOT NULL,
    resultat              JSONB        NOT NULL,
    plantilla_meta        JSONB,       -- només si plantilla = TRUE
    -- Traçabilitat: usuari (oficina/admin) que ha desat l'agrupació.
    -- FK declarat com ALTER més avall perquè la taula `usuaris` es defineix
    -- més endavant en aquest fitxer. NULL si la fila és anterior a l'auth
    -- o si l'usuari s'ha eliminat.
    created_by_id         INTEGER,
    -- Finalització manual: si l'oficina tanca una agrupació encara que no
    -- tots els productes estiguin marcats com a preparats. NULL = no tancada
    -- manualment.
    finalitzada_manual_at      TIMESTAMPTZ,
    finalitzada_manual_per_id  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_agrupacions_ts                ON agrupacions (ts DESC);
CREATE INDEX IF NOT EXISTS idx_agrupacions_plantilla         ON agrupacions (plantilla) WHERE plantilla = TRUE;
CREATE INDEX IF NOT EXISTS idx_agrupacions_created_by        ON agrupacions (created_by_id) WHERE created_by_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agrupacions_finalitzada_manual ON agrupacions (finalitzada_manual_at) WHERE finalitzada_manual_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Productes preparats per agrupació (estat operari magatzem)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS productes_preparats (
    agrupacio_id          UUID         NOT NULL REFERENCES agrupacions(id) ON DELETE CASCADE,
    art_codi              TEXT         NOT NULL,
    marcat_ts             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    marcat_ip             TEXT,
    -- Traçabilitat: usuari que ha marcat el producte. FK declarat com ALTER
    -- més avall (vegeu el comentari a `agrupacions.created_by_id`).
    marcat_per_id         INTEGER,
    PRIMARY KEY (agrupacio_id, art_codi)
);

CREATE INDEX IF NOT EXISTS idx_productes_preparats_agrupacio  ON productes_preparats (agrupacio_id);
CREATE INDEX IF NOT EXISTS idx_productes_preparats_marcat_per ON productes_preparats (marcat_per_id) WHERE marcat_per_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Índex desnormalitzat: quines càrregues són en quina agrupació
-- (permet trobar tota agrupació d'una càrrega en O(1) sense parsejar JSONB)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agrupacio_carregues (
    agrupacio_id          UUID         NOT NULL REFERENCES agrupacions(id) ON DELETE CASCADE,
    carrega_id            TEXT         NOT NULL,
    tra_codi              TEXT,
    PRIMARY KEY (agrupacio_id, carrega_id)
);

CREATE INDEX IF NOT EXISTS idx_agrupacio_carregues_carrega ON agrupacio_carregues (carrega_id);
CREATE INDEX IF NOT EXISTS idx_agrupacio_carregues_tra     ON agrupacio_carregues (tra_codi);

-- ---------------------------------------------------------------------------
-- Comptador global de versió. Una sola fila (id = 1). S'incrementa
-- atòmicament dins de cada transacció que escriu a `agrupacions`,
-- `agrupacio_carregues` o `productes_preparats`. Permet que workers
-- Gunicorn diferents detectin canvis fets pels altres workers sense
-- compartir memòria (el cache d'index_carregues_agrupades es valida
-- contra aquesta versió).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta_agrupacions (
    id      SMALLINT  PRIMARY KEY CHECK (id = 1),
    version BIGINT    NOT NULL DEFAULT 0
);
INSERT INTO meta_agrupacions (id, version) VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Usuaris locals (Phase D de seguretat). Login via password_hash PBKDF2-SHA256.
-- Rol controla l'accés a recursos d'administració. `actiu = FALSE` bloqueja
-- el login sense haver d'esborrar la fila (conservem audit history).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuaris (
    id            SERIAL       PRIMARY KEY,
    username      TEXT         NOT NULL UNIQUE,
    password_hash TEXT         NOT NULL,
    nom           TEXT         NOT NULL,
    rol           TEXT         NOT NULL DEFAULT 'oficina',  -- 'admin' | 'oficina' | 'magatzem'
    actiu         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

-- FK de traçabilitat: declarats com ALTER TABLE perquè `agrupacions` i
-- `productes_preparats` es defineixen abans que `usuaris`. Embolcallats en
-- DO blocks per ser idempotents (PG12 no té ADD CONSTRAINT IF NOT EXISTS).
DO $$ BEGIN
    ALTER TABLE agrupacions
        ADD CONSTRAINT fk_agrupacions_created_by
        FOREIGN KEY (created_by_id) REFERENCES usuaris(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE productes_preparats
        ADD CONSTRAINT fk_productes_preparats_marcat_per
        FOREIGN KEY (marcat_per_id) REFERENCES usuaris(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE agrupacions
        ADD CONSTRAINT fk_agrupacions_finalitzada_manual_per
        FOREIGN KEY (finalitzada_manual_per_id) REFERENCES usuaris(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_productes_preparats_marcat_per
    ON productes_preparats (marcat_per_id) WHERE marcat_per_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Audit log: registre d'accions importants (escriptures) per a traçabilitat.
-- Cada fila és una acció executada per un usuari (o NULL si encara no hi ha
-- autenticació). El camp detall és JSONB per a flexibilitat futura.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id        BIGSERIAL    PRIMARY KEY,
    ts        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    user_id   INTEGER,
    user_name TEXT,
    ip        INET,
    accio     TEXT         NOT NULL,
    target    TEXT,
    detall    JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_ts    ON audit_logs (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_accio ON audit_logs (accio);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user  ON audit_logs (user_id) WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Nota SAP: les taules `kais_carrega_snapshot` i `kais_carrega_override`
-- que hi ha a la variant KAIS no s'apliquen aqui. SAP B1 no sobreescriu
-- U_SEIDataS quan la carrega canvia d'estat, aixi que no cal snapshot ni
-- override manual de la data planificada.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Vista: una agrupació es considera "finalitzada" si l'oficina l'ha tancada
-- manualment (finalitzada_manual_at NOT NULL) o si tots els productes ja
-- estan marcats com a preparats.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_agrupacions_estat AS
SELECT
    a.id,
    a.nom,
    a.ts,
    a.plantilla,
    a.n_productes,
    COALESCE(p.n_preparats, 0) AS n_preparats,
    (
        a.finalitzada_manual_at IS NOT NULL
        OR (a.n_productes > 0 AND COALESCE(p.n_preparats, 0) >= a.n_productes)
    ) AS finalitzada,
    a.finalitzada_manual_at,
    a.finalitzada_manual_per_id
FROM agrupacions a
LEFT JOIN (
    SELECT agrupacio_id, COUNT(*)::INTEGER AS n_preparats
    FROM productes_preparats
    GROUP BY agrupacio_id
) p ON p.agrupacio_id = a.id;
