import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body

from app.assistant import (
    ask_thread,
    build_digest,
    make_draft,
    make_summary,
    read_digest,
    set_task_done,
)
from app.config import settings
from app.db import db
from app.errors import AppError
from app.llm import ollama_status
from app.mail import load_mock_messages, probe_imap
from app.settings_store import effective, public_settings, save_settings, validate_settings
from app.sync_service import clear_mailbox, mailbox_key, start_sync, sync_status
from app.textutil import from_name, preview

logger = logging.getLogger("ingosight.api")
router = APIRouter()


def _purge_history(conn) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("DELETE FROM summaries WHERE created_at < ?", (cutoff,))
    conn.execute("DELETE FROM drafts WHERE created_at < ?", (cutoff,))


def prepare_database() -> None:
    folder = os.path.dirname(settings.database_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    from app.db import init_db

    init_db()
    with db() as conn:
        _purge_history(conn)


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/settings")
def get_settings() -> dict:
    return public_settings()


@router.put("/api/settings")
def put_settings(payload: dict = Body(...)) -> dict:
    previous = mailbox_key(effective())
    saved = save_settings(payload)
    if mailbox_key(effective()) != previous:
        clear_mailbox()
    return saved


@router.post("/api/settings/test-imap")
def test_imap(payload: dict = Body(...)) -> dict:
    current = effective()
    cleaned = validate_settings(payload, require_host=True)
    current.update(cleaned)
    if str(payload.get("imap_password") or "").strip():
        current["imap_password"] = str(payload["imap_password"])
    if current["imap_mode"] == "mock":
        if not os.path.isdir(settings.fixtures_dir):
            raise AppError(
                "IMAP_ERROR",
                "Не удалось подключиться к почте. Проверьте настройки",
                502,
            )
        load_mock_messages(settings.fixtures_dir, int(current["sync_days"]))
        return {"ok": True, "message": "Подключение успешно"}
    if not current["imap_host"] or not current["imap_user"] or not current["imap_password"]:
        raise AppError(
            "IMAP_ERROR",
            "Не удалось подключиться к почте. Проверьте настройки",
            502,
        )
    try:
        probe_imap(
            current["imap_host"],
            int(current["imap_port"]),
            bool(current["imap_ssl"]),
            current["imap_user"],
            current["imap_password"],
        )
    except Exception:
        logger.info("imap probe failed host=%s code=IMAP_ERROR", current["imap_host"])
        raise AppError(
            "IMAP_ERROR",
            "Не удалось подключиться к почте. Проверьте настройки",
            502,
        )
    return {"ok": True, "message": "Подключение успешно"}


@router.get("/api/ollama/status")
def ollama() -> dict:
    return ollama_status()


@router.post("/api/sync", status_code=202)
def post_sync() -> dict:
    return start_sync()


@router.get("/api/sync/status")
def get_sync_status() -> dict:
    return sync_status()


def _like(query: str) -> str:
    safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{safe}%"


@router.get("/api/threads")
def list_threads(limit: int = 25, offset: int = 0, q: str = "") -> dict:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    query = q.strip()
    pattern = _like(query) if query else "%"
    with db() as conn:
        total = conn.execute(
            """
            SELECT COUNT(*) AS count FROM threads
            WHERE ? = '' OR subject LIKE ? ESCAPE '\\' OR participants LIKE ? ESCAPE '\\'
            """,
            (query, pattern, pattern),
        ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT id, subject, participants, last_message_at,
                (SELECT COUNT(*) FROM messages WHERE messages.thread_id = threads.id) AS message_count,
                (
                    SELECT body_text FROM messages
                    WHERE messages.thread_id = threads.id
                    ORDER BY date DESC, id DESC LIMIT 1
                ) AS last_body
            FROM threads
            WHERE ? = '' OR subject LIKE ? ESCAPE '\\' OR participants LIKE ? ESCAPE '\\'
            ORDER BY last_message_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (query, pattern, pattern, limit, offset),
        ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "subject": row["subject"],
                "participants": row["participants"] or "",
                "message_count": row["message_count"],
                "last_message_at": row["last_message_at"],
                "last_message_preview": preview(row["last_body"] or "", 140),
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/threads/{thread_id}")
def get_thread(thread_id: int) -> dict:
    with db() as conn:
        thread = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if thread is None:
            raise AppError("NOT_FOUND", "Тред не найден", 404)
        messages = conn.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY date, id",
            (thread_id,),
        ).fetchall()
        summary = conn.execute(
            """
            SELECT summary_text, source_hash, created_at FROM summaries
            WHERE thread_id = ? ORDER BY id DESC LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
        draft = conn.execute(
            """
            SELECT draft_text, source_hash, created_at FROM drafts
            WHERE thread_id = ? ORDER BY id DESC LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
    import hashlib

    payload = "|".join(f"{row['message_id']}:{row['body_text']}" for row in messages)
    current_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {
        "id": thread["id"],
        "subject": thread["subject"],
        "participants": thread["participants"] or "",
        "messages": [
            {
                "id": row["id"],
                "from_addr": row["from_addr"],
                "from_name": from_name(row["from_addr"] or ""),
                "to_addr": row["to_addr"],
                "date": row["date"],
                "subject": row["subject"],
                "body_text": row["body_text"] or "",
                "preview": preview(row["body_text"] or "", 280),
                "attachments": _attachments(row["attachments"]),
            }
            for row in messages
        ],
        "summary": None
        if summary is None
        else {
            "text": summary["summary_text"],
            "created_at": summary["created_at"],
            "stale": summary["source_hash"] != current_hash,
        },
        "draft": None
        if draft is None
        else {
            "text": draft["draft_text"],
            "created_at": draft["created_at"],
            "stale": draft["source_hash"] != current_hash,
        },
    }


def _attachments(raw: str | None) -> list[str]:
    if not raw:
        return []
    import json

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


@router.post("/api/threads/{thread_id}/summary")
def post_summary(thread_id: int) -> dict:
    return make_summary(thread_id)


@router.post("/api/threads/{thread_id}/ask")
def post_ask(thread_id: int, payload: dict = Body(...)) -> dict:
    return ask_thread(thread_id, str(payload.get("question") or ""))


@router.post("/api/threads/{thread_id}/draft")
def post_draft(thread_id: int, payload: dict = Body(...)) -> dict:
    return make_draft(thread_id, str(payload.get("tone") or "деловой"))


@router.get("/api/digest")
def get_digest() -> dict:
    return read_digest()


@router.post("/api/digest")
def post_digest() -> dict:
    return build_digest()


@router.patch("/api/tasks/{task_id}")
def patch_task(task_id: int, payload: dict = Body(...)) -> dict:
    if "is_done" not in payload or not isinstance(payload["is_done"], bool):
        raise AppError(
            "VALIDATION_ERROR",
            "Проверьте отмеченные поля",
            422,
            {"fields": ["is_done"]},
        )
    return set_task_done(task_id, payload["is_done"])
