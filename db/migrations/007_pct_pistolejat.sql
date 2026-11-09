-- % de kg pistolejats per l'SGA de cada agrupacio (0-100).
-- Idempotent (IF NOT EXISTS): es pot aplicar sense risc sobre una BD ja migrada.
--
-- El desa preparacio_sga.py (pantalla de preparacio i timer del pistolejat)
-- perque la pagina principal pugui ensenyar l'avanc parcial ("en preparacio
-- · 35%") sense consultar SAP per a cada agrupacio. NULL = encara no s'ha
-- sincronitzat mai.

ALTER TABLE agrupacions ADD COLUMN IF NOT EXISTS pct_pistolejat SMALLINT;
