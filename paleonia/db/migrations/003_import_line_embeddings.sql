-- Traz o índice antigo, criado antes das migrations, se a tabela ainda existir.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'line_embeddings'
    ) THEN
        INSERT INTO transcriptions (
            page_id, page_name, line_id, part_id, linha_documento, linha_transcrita,
            text, content_hash, embedding
        )
        SELECT
            page_id, page_name, line_id, part_id, linha_documento, linha_transcrita,
            text, content_hash, embedding
        FROM line_embeddings
        ON CONFLICT (part_id) DO NOTHING;
        DROP TABLE line_embeddings;
    END IF;
END $$;
