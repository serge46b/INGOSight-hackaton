import logging
import threading

import httpx

from app.config import settings
from app.errors import AppError
from app.settings_store import effective

logger = logging.getLogger("ingosight.llm")
_lock = threading.Lock()


def _busy() -> None:
    raise AppError(
        "MODEL_BUSY",
        "Дождитесь завершения текущей генерации",
        429,
    )


def _acquire() -> None:
    if not _lock.acquire(blocking=False):
        _busy()


def ollama_status() -> dict:
    url = settings.ollama_url.rstrip("/")
    try:
        response = httpx.get(f"{url}/api/tags", timeout=4)
        response.raise_for_status()
        names = [item.get("name", "") for item in response.json().get("models", [])]
        model = effective()["model_name"]
        present = any(model.split(":")[0] in name for name in names)
        host = url.replace("http://", "").replace("https://", "")
        if present:
            return {"ok": True, "detail": f"Ollama подключена ({host})"}
        return {"ok": True, "detail": f"Ollama подключена ({host}), модель {model} ещё скачивается"}
    except Exception:
        logger.info("ollama status failed code=LLM_ERROR")
        return {"ok": False, "detail": "Модель недоступна"}


def _post(path: str, payload: dict, timeout: float) -> dict:
    url = settings.ollama_url.rstrip("/") + path
    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except httpx.TimeoutException as exc:
        logger.info("ollama timeout code=LLM_ERROR")
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        ) from exc
    except httpx.HTTPError as exc:
        logger.info("ollama network code=LLM_ERROR")
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        ) from exc
    if response.status_code >= 400:
        body = response.text.lower()
        if "memory" in body or "cuda" in body or "out of memory" in body:
            raise AppError("LLM_OOM", "cuda oom", 503)
        logger.info("ollama http %s code=LLM_ERROR", response.status_code)
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        )
    return response.json()


def generate(prompt: str) -> str:
    model = effective()["model_name"]
    _acquire()
    try:
        options = {"temperature": 0.2, "num_ctx": 4096}
        try:
            data = _post(
                "/api/chat",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": options,
                },
                timeout=180,
            )
        except AppError as exc:
            if exc.code != "LLM_OOM":
                raise
            logger.info("ollama gpu busy, retry on cpu")
            data = _post(
                "/api/chat",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {**options, "num_gpu": 0},
                },
                timeout=300,
            )
        content = ((data.get("message") or {}).get("content") or "").strip()
        return content
    except AppError as exc:
        if exc.code == "LLM_OOM":
            raise AppError(
                "LLM_ERROR",
                "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
                503,
            ) from exc
        raise
    finally:
        _lock.release()


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = settings.embed_model
    _acquire()
    try:
        try:
            data = _post("/api/embed", {"model": model, "input": texts}, timeout=180)
            vectors = data.get("embeddings") or []
            if len(vectors) == len(texts):
                return vectors
        except AppError as exc:
            if exc.code == "LLM_OOM":
                data = _post(
                    "/api/embed",
                    {"model": model, "input": texts, "options": {"num_gpu": 0}},
                    timeout=300,
                )
                vectors = data.get("embeddings") or []
                if len(vectors) == len(texts):
                    return vectors
            elif exc.code != "LLM_ERROR":
                raise
        vectors = []
        for text in texts:
            data = _post("/api/embeddings", {"model": model, "prompt": text}, timeout=120)
            vector = data.get("embedding")
            if not vector:
                raise AppError(
                    "LLM_ERROR",
                    "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
                    503,
                )
            vectors.append(vector)
        return vectors
    except AppError as exc:
        if exc.code == "LLM_OOM":
            raise AppError(
                "LLM_ERROR",
                "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
                503,
            ) from exc
        raise
    finally:
        _lock.release()
