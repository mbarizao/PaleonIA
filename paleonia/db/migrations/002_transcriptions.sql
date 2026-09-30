-- A coluna de vetor fica em 768 dimensões (nomic-embed-text).
-- Outro tamanho pede uma migration nova e EMBED_DIMENSIONS igual.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE transcriptions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT REFERENCES users (id) ON DELETE CASCADE,
    page_id TEXT NOT NULL,
    page_name TEXT NOT NULL,
    line_id TEXT NOT NULL,
    part_id TEXT NOT NULL UNIQUE,
    linha_documento INTEGER,
    linha_transcrita INTEGER,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding vector(768),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX transcriptions_page ON transcriptions (page_id);

CREATE INDEX transcriptions_user ON transcriptions (user_id);

CREATE INDEX transcriptions_cosine ON transcriptions USING hnsw (embedding vector_cosine_ops);
