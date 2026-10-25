import gzip
import json

import app.data as data


def test_reads_local_jsonl_first_then_falls_back_to_snapshot(tmp_path, monkeypatch):
    chunks_dir, snapshot_dir = tmp_path / "chunks", tmp_path / "snapshot"
    chunks_dir.mkdir()
    snapshot_dir.mkdir()
    monkeypatch.setattr(data, "CHUNKS_DIR", chunks_dir)
    monkeypatch.setattr(data, "SNAPSHOT_DIR", snapshot_dir)

    with gzip.open(snapshot_dir / "s.jsonl.gz", "wt") as f:
        f.write(json.dumps({"chunk_id": "from-snapshot"}) + "\n")
    assert data.read_chunks("s") == [{"chunk_id": "from-snapshot"}]

    (chunks_dir / "s.jsonl").write_text(json.dumps({"chunk_id": "local"}) + "\n")
    assert data.read_chunks("s") == [{"chunk_id": "local"}]
