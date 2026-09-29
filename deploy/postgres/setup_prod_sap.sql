-- =====================================================================
-- Setup PostgreSQL de PRODUCCIO — variant SAP B1
-- =====================================================================
-- El deploy.sh --first-install fa aquests passos automaticament amb una
-- contrasenya generada. Aquest fitxer serveix per fer-ho a ma o per
-- entendre que s'ha creat.
--
-- Executar com a superuser:  sudo -u postgres psql -f setup_prod_sap.sql
-- Abans: substituir CANVIA_AQUESTA_CONTRASENYA.
--
-- La BD es SEPARADA de la de Kais (agrupaciocarregues): els carrega_id de
-- SAP i de Kais no son compatibles i barrejar-los corromp les agrupacions.
-- =====================================================================

-- --- Rol de l'aplicacio -------------------------------------------------
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_agrupacions_sap') THEN
      CREATE ROLE app_agrupacions_sap WITH LOGIN PASSWORD 'CANVIA_AQUESTA_CONTRASENYA';
   END IF;
END
$$;

-- --- Base de dades ------------------------------------------------------
-- CREATE DATABASE no pot anar dins d'un bloc DO ni d'una transaccio.
CREATE DATABASE agrupaciocarregues_sap OWNER app_agrupacions_sap ENCODING 'UTF8';

GRANT ALL PRIVILEGES ON DATABASE agrupaciocarregues_sap TO app_agrupacions_sap;

-- =====================================================================
-- Connectar-se ARA a la BD nova (\c agrupaciocarregues_sap) i executar:
-- =====================================================================
-- PostgreSQL 15+: el schema `public` no es escrivible pel propietari de la
-- BD per defecte. Sense aixo, carregar schema.sql falla amb
-- "permission denied for schema public".
--
--   ALTER SCHEMA public OWNER TO app_agrupacions_sap;
--   GRANT CREATE, USAGE ON SCHEMA public TO app_agrupacions_sap;
--
-- I despres, com a app_agrupacions_sap (perque les taules siguin seves):
--   psql -h localhost -U app_agrupacions_sap -d agrupaciocarregues_sap -f db/schema.sql
--   psql ... -f db/migrations/002_user_tracking.sql
--   psql ... -f db/migrations/003_finalitzacio_manual.sql
--   psql ... -f db/migrations/004_origen_agrupacions.sql
--   psql ... -f db/migrations/005_carrega_data_planificada.sql
-- (totes les migracions son idempotents)
-- =====================================================================
