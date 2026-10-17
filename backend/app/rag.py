import logging

from app.config import settings
from app.llm import embed_texts
from app.textutil import chunk_text

logger = logging.getLogger("ingosight.rag")
_collection = None


def _collection_handle():
    global _collection
    if _collection is not None:
        return _collection
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    _collection = client.get_or_create_collection(
        name="mail_chunks",
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def reset_index() -> None:
    global _collection
    _collection = None
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        client.delete_collection("mail_chunks")
    except Exception:
        logger.info("chroma reset skipped")


def index_message(thread_id: int, message_id: int, text: str) -> None:
    chunks = chunk_text(text, settings.context_chunk_tokens, settings.context_overlap_tokens)
    collection = _collection_handle()
    try:
        collection.delete(where={"message_id": message_id})
    except Exception:
        logger.info("chroma delete skipped message_id=%s", message_id)
    if not chunks:
        return
    vectors = embed_texts(chunks)
    collection.upsert(
        ids=[f"{message_id}:{index}" for index in range(len(chunks))],
        documents=chunks,
        embeddings=vectors,
        metadatas=[
            {"thread_id": int(thread_id), "message_id": int(message_id), "chunk": index}
            for index in range(len(chunks))
        ],
    )


def search_thread(thread_id: int, question: str, limit: int | None = None) -> list[str]:
    top_k = limit or settings.rag_top_k
    vector = embed_texts([question])[0]
    result = _collection_handle().query(
        query_embeddings=[vector],
        n_results=top_k,
        where={"thread_id": int(thread_id)},
    )
    documents = (result.get("documents") or [[]])[0]
    return [doc for doc in documents if doc]
