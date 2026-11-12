-- Qui ha cancel·lat cada albara des de "Gestio d'albarans".
-- Idempotent (IF NOT EXISTS): es pot aplicar sense risc sobre una BD ja migrada.
--
-- A SAP la cancel·lacio la signa l'usuari del Service Layer; aqui hi queda
-- l'operari de magatzem que l'ha feta (nomes el nom, mai el seu codi). La
-- pantalla d'albarans l'ensenya al costat de l'estat "Cancel·lat".

CREATE TABLE IF NOT EXISTS albarans_cancelats (
    docentry    INTEGER     PRIMARY KEY,
    docnum      INTEGER     NOT NULL,
    operari_nom TEXT        NOT NULL,
    motiu       TEXT,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
