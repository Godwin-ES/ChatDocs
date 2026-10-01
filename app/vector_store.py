"""Pinecone-backed document store used for both ingestion and agent retrieval.

Compared with Agno's stock PineconeDb this store:
- embeds chunks in batches instead of one HTTP call per chunk,
- adds the "query: " / "passage: " prefixes the e5 embedding model was trained with,
- optionally runs hybrid (dense + BM25 keyword) search on dotproduct indexes,
- shares one Pinecone index connection across requests,
- gives chunks predictable ids ("<doc key>#<n>") so a document can be deleted by id prefix.
"""
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import numpy as np
from agno.knowledge.document import Document
from agno.vectordb.pineconedb import PineconeDb

logger = logging.getLogger("rag-app")

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
EMBED_BATCH_SIZE = 32
UPSERT_BATCH_SIZE = 100

# Bumped whenever the way chunks are embedded changes; documents indexed with an
# older version should be re-indexed (see app/reindex.py).
INDEX_VERSION = 2


def doc_key(filename: str) -> str:
    return hashlib.sha1(filename.encode("utf-8")).hexdigest()[:16]


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class Embeddings:
    """Batch embedding on top of the Hugging Face inference client."""

    def __init__(self, hf_embedder, dimensions: int):
        self.hf = hf_embedder
        self.dimensions = dimensions

    def _call(self, texts: List[str]) -> np.ndarray:
        result = np.asarray(self.hf.client.feature_extraction(text=texts, model=self.hf.id), dtype="float32")
        if result.ndim == 1:
            result = result.reshape(1, -1)
        if result.shape != (len(texts), self.dimensions):
            raise ValueError(f"Unexpected embedding shape {result.shape} for {len(texts)} texts")
        return result

    def _embed_batch(self, texts: List[str]) -> np.ndarray:
        try:
            return self._call(texts)
        except Exception:
            if len(texts) == 1:
                raise
            # Some inference backends reject list inputs; fall back to parallel single calls.
            logger.warning("Batch embedding failed, falling back to per-text requests", exc_info=True)
            with ThreadPoolExecutor(max_workers=8) as pool:
                return np.vstack(list(pool.map(lambda t: self._call([t]), texts)))

    def embed(self, texts: List[str]) -> np.ndarray:
        batches = [texts[i:i + EMBED_BATCH_SIZE] for i in range(0, len(texts), EMBED_BATCH_SIZE)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            vectors = np.vstack(list(pool.map(self._embed_batch, batches)))
        return _normalize(vectors)

    def embed_passages(self, texts: List[str]) -> List[List[float]]:
        return self.embed([PASSAGE_PREFIX + t for t in texts]).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.embed([QUERY_PREFIX + text])[0].tolist()


class SparseEncoder:
    """Lazily loads the BM25 keyword encoder once per process (it is downloaded on load)."""

    def __init__(self):
        self._encoder = None
        self._failed = False
        self._lock = threading.Lock()

    def get(self):
        if self._encoder is None and not self._failed:
            with self._lock:
                if self._encoder is None and not self._failed:
                    try:
                        from pinecone_text.sparse import BM25Encoder
                        self._encoder = BM25Encoder.default()
                    except Exception:
                        logger.exception("Could not load the BM25 encoder; using dense-only search")
                        self._failed = True
        return self._encoder


def _flat_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Pinecone metadata values must be strings, numbers, booleans or lists of strings."""
    flat = {}
    for key, value in (meta or {}).items():
        if isinstance(value, (str, int, float, bool)):
            flat[key] = value
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            flat[key] = value
    return flat


class DocumentStore(PineconeDb):
    """A per-user view (one Pinecone namespace) over the shared index."""

    def __init__(self, *, index, embeddings: Embeddings, sparse: Optional[SparseEncoder],
                 hybrid_alpha: float, namespace: str, **kwargs):
        super().__init__(embedder=embeddings.hf, namespace=namespace, **kwargs)
        self._index = index  # shared connection; avoids a describe_index call per request
        self.embeddings = embeddings
        self.sparse = sparse
        self.hybrid_alpha = hybrid_alpha

    # --- Ingestion ---
    def index_document(self, filename: str, documents: List[Document]) -> int:
        """Replaces all chunks of `filename` with `documents`. Returns the number of chunks stored."""
        chunks = [d for d in documents if d.content and d.content.strip()]
        if not chunks:
            return 0

        dense = self.embeddings.embed_passages([d.content for d in chunks])
        encoder = self.sparse.get() if self.sparse else None
        key = doc_key(filename)

        vectors = []
        for i, (chunk, values) in enumerate(zip(chunks, dense)):
            metadata = _flat_metadata(chunk.meta_data)
            metadata.update({"name": filename, "text": chunk.content, "chunk_index": i})
            vector = {"id": f"{key}#{i}", "values": values, "metadata": metadata}
            if encoder is not None:
                sparse = encoder.encode_documents(chunk.content)
                if sparse.get("indices"):
                    vector["sparse_values"] = sparse
            vectors.append(vector)

        # Remove the previous version first so a shorter new file leaves no stale chunks.
        self.delete_document(filename)
        for i in range(0, len(vectors), UPSERT_BATCH_SIZE):
            self._index.upsert(vectors=vectors[i:i + UPSERT_BATCH_SIZE], namespace=self.namespace)
        return len(vectors)

    def delete_document(self, filename: str) -> None:
        for ids in self._index.list(prefix=f"{doc_key(filename)}#", namespace=self.namespace):
            if ids:
                self._index.delete(ids=ids, namespace=self.namespace)
        # Chunks indexed before INDEX_VERSION 2 used Agno-generated ids; remove those by name.
        try:
            self._index.delete(filter={"name": {"$eq": filename}}, namespace=self.namespace)
        except Exception:
            logger.debug("Metadata delete not supported on this index", exc_info=True)

    # --- Retrieval (called by the agent's search_knowledge_base tool) ---
    def search(self, query: str, limit: int = 5, filters=None, namespace: Optional[str] = None,
               include_values: Optional[bool] = None) -> List[Document]:
        if not isinstance(filters, dict):
            filters = None
        dense = self.embeddings.embed_query(query)
        params = dict(top_k=limit, namespace=namespace or self.namespace, filter=filters, include_metadata=True)

        encoder = self.sparse.get() if self.sparse else None
        sparse = encoder.encode_queries(query) if encoder is not None else None
        if sparse and sparse.get("indices"):
            a = self.hybrid_alpha
            params["vector"] = [v * a for v in dense]
            params["sparse_vector"] = {"indices": sparse["indices"], "values": [v * (1 - a) for v in sparse["values"]]}
        else:
            params["vector"] = dense

        response = self._index.query(**params)
        results = []
        for match in response.matches:
            meta = dict(match.metadata or {})
            text = meta.pop("text", "")  # returned as content; don't send it to the model twice
            results.append(Document(content=text, id=match.id, name=meta.get("name"), meta_data=meta))
        return results

    async def async_search(self, *args, **kwargs) -> List[Document]:
        import asyncio
        return await asyncio.to_thread(self.search, *args, **kwargs)
