"""Phase 3: turn text into 384-number "meaning vectors" with a free local model.

BAAI/bge-small-en-v1.5 is also hosted on Cloudflare Workers AI
(@cf/baai/bge-small-en-v1.5), so production can embed queries with the same
model. sentence-transformers uses CLS pooling for this model, so the Workers
AI call must pass pooling="cls" or the vectors won't line up.
"""

from functools import lru_cache

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
# BGE v1.5 is trained with this instruction on queries (not on passages).
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def get_model():
    import torch
    from sentence_transformers import SentenceTransformer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    return SentenceTransformer(MODEL_NAME, device=device)


def embed_passages(texts: list[str], batch_size: int = 64) -> np.ndarray:
    return get_model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,  # unit length, so cosine similarity = dot product
        show_progress_bar=True,
    )


def embed_query(query: str) -> np.ndarray:
    return get_model().encode(QUERY_INSTRUCTION + query, normalize_embeddings=True)


def passage_text(chunk: dict, doc: dict) -> str:
    """What we actually embed: the chunk plus which grant and section it's from.

    A chunk like "No." means nothing alone; "Cost Sharing Required? No." in
    grant X does. The stored chunk text stays unchanged for quoting.
    """
    header = [f"Grant: {doc['title']}", f"Agency: {doc['agency']}"]
    if chunk.get("section"):
        header.append(f"Section: {chunk['section']}")
    return "\n".join(header) + "\n\n" + chunk["text"]
