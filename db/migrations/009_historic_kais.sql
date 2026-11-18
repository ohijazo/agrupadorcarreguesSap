-- Historic de carregues de KAIS (els tres mesos abans del 23/11/2026).
-- Idempotent (IF NOT EXISTS): es pot aplicar sense risc sobre una BD ja migrada.
--
-- KAIS deixa de fer-se servir el 23/11/2026. Perque l'usuari no noti el canvi,
-- el calendari continua ensenyant les carregues d'abans, copiades aqui el dia
-- del canvi per `scripts/importar_historic_kais.py`. Es una copia congelada: a
-- KAIS ja no s'hi fa res, i aixi l'app no en depen.
--
--   item    = el que retornava /api/carregues de l'app de KAIS
--   detall  = el que retornava /api/carrega-detall (NULL si no se'n va poder treure)
--   data_cal = car_fecsalida (o car_fecha), la data per on filtrava KAIS

CREATE TABLE IF NOT EXISTS historic_carregues (
    carrega_id   TEXT         PRIMARY KEY,
    data_cal     DATE         NOT NULL,
    item         JSONB        NOT NULL,
    detall       JSONB,
    importat_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_historic_carregues_data
    ON historic_carregues (data_cal);
