-- Phase 0/1 schema. The chunks table (with the vector column) arrives in
-- Phase 3, once we've picked an embedding model and know its dimension.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    opportunity_id          BIGINT PRIMARY KEY,
    opportunity_number      TEXT,
    title                   TEXT NOT NULL,
    agency_code             TEXT,
    agency                  TEXT,
    status                  TEXT,
    open_date               DATE,
    close_date              DATE,
    award_ceiling           BIGINT,
    award_floor             BIGINT,
    estimated_total_funding BIGINT,
    categories              TEXT[],
    applicant_types         TEXT[],
    cfda_numbers            TEXT[],
    source_url              TEXT,
    pdf_url                 TEXT,
    pdf_file                TEXT NOT NULL,
    pdf_sha256              TEXT UNIQUE,
    pdf_bytes               BIGINT
);

-- Phase 3: chunks + embeddings. chunk_set names the chunking run
-- (e.g. section_300, fixed_300) so experiments can live side by side.
-- 384 = output size of BAAI/bge-small-en-v1.5.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_set      TEXT NOT NULL,
    chunk_id       TEXT NOT NULL,
    opportunity_id BIGINT NOT NULL REFERENCES documents (opportunity_id) ON DELETE CASCADE,
    chunk_index    INT NOT NULL,
    section        TEXT,
    page_start     INT,
    page_end       INT,
    text           TEXT NOT NULL,
    n_words        INT,
    embedding      vector(384) NOT NULL,
    -- Keyword index for hybrid search (Phase 5).
    tsv            tsvector GENERATED ALWAYS AS (
                       to_tsvector('english', coalesce(section, '') || ' ' || text)
                   ) STORED,
    PRIMARY KEY (chunk_set, chunk_id)
);

-- HNSW: graph index for fast approximate nearest-neighbour search by cosine distance.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_opportunity ON chunks (opportunity_id);
