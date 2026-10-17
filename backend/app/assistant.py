import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db import db
from app.errors import AppError
from app.llm import generate
from app.rag import search_thread
from app.settings_store import ALLOWED_TONES, effective, get_json_setting, set_json_setting
from app.textutil import from_name, postprocess, preview

logger = logging.getLogger("ingosight.assistant")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _messages(conn, thread_id: int):
    return conn.execute(
        "SELECT * FROM messages WHERE thread_id = ? ORDER BY date, id",
        (thread_id,),
    ).fetchall()


def _require_thread(conn, thread_id: int):
    row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if row is None:
        raise AppError("NOT_FOUND", "Тред не найден", 404)
    return row


def _source_hash(rows) -> str:
    payload = "|".join(f"{row['message_id']}:{row['body_text']}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_letters(rows) -> str:
    parts = []
    for row in rows:
        parts.append(
            "\n".join(
                [
                    f"От: {row['from_addr']}",
                    f"Дата: {row['date']}",
                    f"Тема: {row['subject']}",
                    row["body_text"] or "",
                ]
            )
        )
    return "\n---\n".join(parts)


def _ensure_fits(text: str) -> None:
    if len(text) > settings.context_char_limit:
        raise AppError(
            "CONTEXT_TOO_LONG",
            "Переписка слишком длинная. Сократите период",
            400,
        )


def _clean_model_text(raw: str) -> str:
    text = postprocess(raw, settings.max_output_chars)
    if not text.strip():
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        )
    return text


def make_summary(thread_id: int) -> dict:
    with db() as conn:
        _require_thread(conn, thread_id)
        rows = _messages(conn, thread_id)
        before = _source_hash(rows)
    if not rows:
        raise AppError("NOT_FOUND", "Тред не найден", 404)
    letters = _format_letters(rows)
    _ensure_fits(letters)
    prompt = (
        "Ты — ассистент. Сделай краткое саммари переписки. "
        "Выдели договорённости и открытые вопросы. Пиши на русском. "
        "Не выдумывай факты, которых нет в переписке.\n"
        "Формат:\nТема:\n<одна строка>\nДоговорённости:\n- ...\nОткрытые вопросы:\n- ...\n\n"
        f"Переписка:\n{letters}"
    )
    text = _clean_model_text(generate(prompt))
    with db() as conn:
        rows_after = _messages(conn, thread_id)
        if _source_hash(rows_after) == before:
            conn.execute(
                """
                INSERT INTO summaries(thread_id, summary_text, source_hash, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (thread_id, text, before, _now()),
            )
    logger.info("summary stored thread_id=%s", thread_id)
    return {"summary_text": text}


def ask_thread(thread_id: int, question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise AppError(
            "VALIDATION_ERROR",
            "Проверьте отмеченные поля",
            422,
            {"fields": ["question"]},
        )
    with db() as conn:
        _require_thread(conn, thread_id)
        rows = _messages(conn, thread_id)
    if not rows:
        raise AppError("NOT_FOUND", "Тред не найден", 404)
    try:
        chunks = search_thread(thread_id, question)
    except AppError:
        chunks = []
    except Exception:
        logger.info("rag search failed code=LLM_ERROR thread_id=%s", thread_id)
        chunks = []
    context = "\n\n".join(chunks).strip()
    if not context:
        context = _format_letters(rows)
    _ensure_fits(context)
    prompt = (
        "Ты — ассистент. Ответь на вопрос по переписке, опираясь только на фрагменты ниже. "
        "Пиши на русском. Если в фрагментах нет ответа, так и скажи. Не выдумывай факты.\n\n"
        f"Фрагменты:\n{context}\n\nВопрос: {question}"
    )
    answer = _clean_model_text(generate(prompt))
    logger.info("ask answered thread_id=%s", thread_id)
    return {"answer": answer}


def make_draft(thread_id: int, tone: str) -> dict:
    selected = (tone or "деловой").strip().lower()
    if selected not in ALLOWED_TONES:
        raise AppError(
            "VALIDATION_ERROR",
            "Проверьте отмеченные поля",
            422,
            {"fields": ["tone"]},
        )
    with db() as conn:
        _require_thread(conn, thread_id)
        rows = _messages(conn, thread_id)
        before = _source_hash(rows)
    if not rows:
        raise AppError("NOT_FOUND", "Тред не найден", 404)
    letters = _format_letters(rows[-5:])
    _ensure_fits(letters)
    prompt = (
        f"Напиши ответ в {selected} тоне. Не выдумывай факты, которых нет в переписке. "
        "Пиши на русском. Не добавляй тему письма и пояснения — только текст письма. "
        "Письмо пишет пользователь «Вы» в ответ на последнее входящее. "
        "Не подписывайся чужим именем и не выдумывай должность. "
        "Если нужна подпись, оставь «С уважением» без вымышленного ФИО.\n\n"
        f"Последние письма:\n{letters}"
    )
    text = _clean_model_text(generate(prompt))
    with db() as conn:
        if _source_hash(_messages(conn, thread_id)) == before:
            conn.execute(
                """
                INSERT INTO drafts(thread_id, draft_text, source_hash, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (thread_id, text, before, _now()),
            )
    logger.info("draft stored thread_id=%s", thread_id)
    return {"draft_text": text}


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        )
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        ) from exc
    if not isinstance(parsed, dict):
        raise AppError(
            "LLM_ERROR",
            "Локальная модель не ответила. Проверьте, запущен ли Ollama.",
            503,
        )
    return parsed


def _thread_meta(conn, thread_id: int):
    return conn.execute(
        """
        SELECT threads.id, threads.subject,
               (SELECT from_addr FROM messages WHERE thread_id = threads.id ORDER BY date DESC, id DESC LIMIT 1) AS from_addr,
               (SELECT date FROM messages WHERE thread_id = threads.id ORDER BY date DESC, id DESC LIMIT 1) AS date
        FROM threads WHERE id = ?
        """,
        (thread_id,),
    ).fetchone()


def build_digest() -> dict:
    hours = int(effective()["digest_hours"])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT messages.thread_id, messages.from_addr, messages.date, messages.subject, messages.body_text,
                   threads.subject AS thread_subject
            FROM messages
            JOIN threads ON threads.id = messages.thread_id
            WHERE messages.date >= ?
            ORDER BY messages.date
            """,
            (cutoff,),
        ).fetchall()
    if not rows:
        payload = {
            "generated_at": _now(),
            "period_hours": hours,
            "urgent": [],
            "waiting": [],
        }
        set_json_setting("last_digest", payload)
        return read_digest()

    catalog_lines = []
    for row in rows:
        snippet = preview(row["body_text"] or "", 400)
        catalog_lines.append(
            f"thread_id={row['thread_id']} | {row['date']} | От: {row['from_addr']} | Тема: {row['thread_subject']}\n{snippet}"
        )
    catalog = "\n\n".join(catalog_lines)
    if len(catalog) > settings.context_char_limit:
        catalog = catalog[-settings.context_char_limit :]
    prompt = (
        "Ты — ассистент по деловой почте. Пиши на русском. "
        f"По письмам за последние {hours} часов выдели срочные письма, задачи и ожидаемые ответы. "
        "Не выдумывай факты, которых нет в письмах. Используй только thread_id из списка. "
        "Письмо с дедлайном, просрочкой или просьбой что-то сделать помести в urgent или tasks. "
        "waiting — только если ждём ответа от другого человека. "
        "Если раздела нет — пустой список. Верни только JSON вида "
        '{"urgent":[{"thread_id":1,"reason":"..."}],'
        '"tasks":[{"thread_id":1,"text":"...","due_date":null}],'
        '"waiting":[{"thread_id":1,"text":"..."}]}\n\n'
        f"Письма:\n{catalog}"
    )
    parsed = _extract_json(generate(prompt))
    urgent = []
    waiting = []
    task_rows = []
    with db() as conn:
        for item in parsed.get("urgent") or []:
            if not isinstance(item, dict):
                continue
            try:
                thread_id = int(item.get("thread_id"))
            except (TypeError, ValueError):
                continue
            meta = _thread_meta(conn, thread_id)
            if meta is None:
                continue
            reason = str(item.get("reason") or "").strip()
            urgent.append(
                {
                    "thread_id": thread_id,
                    "title": reason or meta["subject"],
                    "from_addr": from_name(meta["from_addr"] or ""),
                    "date": meta["date"],
                }
            )
        for item in parsed.get("waiting") or []:
            if not isinstance(item, dict):
                continue
            try:
                thread_id = int(item.get("thread_id"))
            except (TypeError, ValueError):
                continue
            if _thread_meta(conn, thread_id) is None:
                continue
            text = str(item.get("text") or "").strip()
            if text:
                waiting.append({"thread_id": thread_id, "text": text})
        for item in parsed.get("tasks") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            try:
                thread_id = int(item.get("thread_id"))
            except (TypeError, ValueError):
                thread_id = None
            if thread_id is not None and _thread_meta(conn, thread_id) is None:
                thread_id = None
            due = item.get("due_date")
            if not isinstance(due, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                due = None
            task_rows.append((thread_id, text, due))
        conn.execute("DELETE FROM tasks WHERE IFNULL(is_done, 0) = 0")
        for thread_id, text, due in task_rows:
            conn.execute(
                """
                INSERT INTO tasks(message_id, thread_id, text, due_date, is_done)
                VALUES(NULL, ?, ?, ?, 0)
                """,
                (thread_id, text, due),
            )
    set_json_setting(
        "last_digest",
        {
            "generated_at": _now(),
            "period_hours": hours,
            "urgent": urgent,
            "waiting": waiting,
        },
    )
    logger.info("digest stored urgent=%s tasks=%s", len(urgent), len(task_rows))
    return read_digest()


def read_digest() -> dict:
    stored = get_json_setting("last_digest")
    if not isinstance(stored, dict):
        stored = {}
    hours = int(effective()["digest_hours"])
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, thread_id, text, due_date, is_done
            FROM tasks
            ORDER BY is_done, id
            """
        ).fetchall()
    tasks = [
        {
            "id": row["id"],
            "thread_id": row["thread_id"],
            "text": row["text"],
            "due_date": row["due_date"],
            "is_done": bool(row["is_done"]),
        }
        for row in rows
    ]
    return {
        "generated_at": stored.get("generated_at"),
        "period_hours": stored.get("period_hours") or hours,
        "urgent": stored.get("urgent") or [],
        "waiting": stored.get("waiting") or [],
        "tasks": tasks,
    }


def set_task_done(task_id: int, is_done: bool) -> dict:
    with db() as conn:
        row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Данные не найдены", 404)
        conn.execute("UPDATE tasks SET is_done = ? WHERE id = ?", (1 if is_done else 0, task_id))
    return {"id": task_id, "is_done": is_done}


def safe_scheduled_digest() -> None:
    try:
        build_digest()
    except AppError as exc:
        logger.info("scheduled digest failed code=%s", exc.code)
    except Exception:
        logger.info("scheduled digest failed code=LLM_ERROR")
