-- Linha conferida pelo usuário. A busca da mesa continua vendo todo o texto.
-- A ajuda à leitura só consulta confirmed = true.
ALTER TABLE transcriptions
    ADD COLUMN IF NOT EXISTS confirmed BOOLEAN NOT NULL DEFAULT false;
