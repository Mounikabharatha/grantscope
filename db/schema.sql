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
