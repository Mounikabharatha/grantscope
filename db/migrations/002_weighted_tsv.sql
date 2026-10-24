-- Phase 5: keyword index now includes the grant title, weighted so a match in
-- the title (A) counts more than one in the section heading (B) or text (C).
-- A generated column can't read another table, so tsv becomes a plain column
-- filled here and by scripts/embed_chunks.py.
ALTER TABLE chunks DROP COLUMN IF EXISTS tsv;  -- also drops its GIN index
ALTER TABLE chunks ADD COLUMN tsv tsvector;

UPDATE chunks c
SET tsv = setweight(to_tsvector('english', d.title), 'A')
       || setweight(to_tsvector('english', coalesce(c.section, '')), 'B')
       || setweight(to_tsvector('english', c.text), 'C')
FROM documents d
WHERE d.opportunity_id = c.opportunity_id;

CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
ANALYZE chunks;
