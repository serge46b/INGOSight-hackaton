import json
import logging
import threading
from datetime import datetime, timezone

from app.config import settings
from app.crypto import encrypt_secret
from app.db import db
from app.errors import AppError
from app.mail import load_imap_messages, load_mock_messages
from app.rag import index_message
from app.settings_store import effective, set_json_setting
from app.textutil import MailLink, from_name, group_indices, strip_subject

logger = logging.getLogger("ingosight.sync")

_state_lock = threading.Lock()
_state = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "messages": 0,
    "threads": 0,
    "error": None,
    "warning": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_status() -> dict:
    with _state_lock:
        current = dict(_state)
    if current["state"] == "idle" and current["finished_at"] is None:
        from app.settings_store import get_json_setting

        saved = get_json_setting("last_sync")
        if isinstance(saved, dict):
            current.update(saved)
            current["state"] = saved.get("state") or "idle"
    return current


def start_sync() -> dict:
    with _state_lock:
        if _state["state"] == "running":
            return dict(_state)
        _state.update(
            {
                "state": "running",
                "started_at": _now(),
                "finished_at": None,
                "error": None,
                "warning": None,
            }
        )
        snapshot = dict(_state)
    threading.Thread(target=_run_sync, name="mail-sync", daemon=True).start()
    return snapshot


def _finish(state: str, messages: int, threads: int, error: dict | None, warning: str | None) -> None:
    payload = {
        "state": state,
        "started_at": _state["started_at"],
        "finished_at": _now(),
        "messages": messages,
        "threads": threads,
        "error": error,
        "warning": warning,
    }
    with _state_lock:
        _state.update(payload)
    if state == "ok":
        set_json_setting("last_sync", payload)
    logger.info("sync finished state=%s messages=%s threads=%s", state, messages, threads)


def _run_sync() -> None:
    try:
        cfg = effective()
        messages = _fetch(cfg)
        thread_count, message_count, pending = _store(messages, cfg)
        warning = None
        for thread_id, message_id, text in pending:
            try:
                index_message(thread_id, message_id, text)
            except AppError as exc:
                warning = exc.message
                logger.info("index failed code=%s", exc.code)
                break
            except Exception:
                warning = "Не удалось обновить поиск по письмам"
                logger.info("index failed code=LLM_ERROR")
                break
        _finish("ok", message_count, thread_count, None, warning)
    except AppError as exc:
        logger.info("sync failed code=%s", exc.code)
        _finish("error", 0, 0, {"code": exc.code, "message": exc.message}, None)
    except Exception:
        logger.info("sync failed code=IMAP_ERROR")
        _finish(
            "error",
            0,
            0,
            {
                "code": "IMAP_ERROR",
                "message": "Не удалось подключиться к почте. Проверьте настройки",
            },
            None,
        )


def _fetch(cfg: dict):
    if cfg["imap_mode"] == "mock":
        return load_mock_messages(settings.fixtures_dir, int(cfg["sync_days"]))
    if not cfg["imap_host"] or not cfg["imap_user"] or not cfg["imap_password"]:
        raise AppError(
            "IMAP_ERROR",
            "Не удалось подключиться к почте. Проверьте настройки",
            502,
        )
    try:
        return load_imap_messages(
            cfg["imap_host"],
            int(cfg["imap_port"]),
            bool(cfg["imap_ssl"]),
            cfg["imap_user"],
            cfg["imap_password"],
            int(cfg["sync_days"]),
        )
    except AppError:
        raise
    except Exception:
        logger.info("imap fetch failed host=%s", cfg["imap_host"])
        raise AppError(
            "IMAP_ERROR",
            "Не удалось подключиться к почте. Проверьте настройки",
            502,
        )


def _store(messages, cfg: dict):
    links = [
        MailLink(item.message_id, item.in_reply_to, item.references, item.subject)
        for item in messages
    ]
    clusters = group_indices(links) if messages else []
    pending: list[tuple[int, int, str]] = []
    with db() as conn:
        account_id = _ensure_account(conn, cfg)
        existing_rows = conn.execute(
            """
            SELECT messages.id, messages.message_id, messages.thread_id, messages.body_text
            FROM messages
            JOIN threads ON threads.id = messages.thread_id
            WHERE threads.account_id = ?
            """,
            (account_id,),
        ).fetchall()
        existing = {row["message_id"]: row for row in existing_rows}
        for cluster in clusters:
            members = [messages[index] for index in cluster]
            known = []
            for member in members:
                row = existing.get(member.message_id)
                if row is not None:
                    known.append(row["thread_id"])
            if known:
                keeper = min(known)
                for other in set(known):
                    if other != keeper:
                        _move_thread(conn, other, keeper)
            else:
                keeper = conn.execute(
                    """
                    INSERT INTO threads(account_id, subject, participants, last_message_at)
                    VALUES(?, ?, '', NULL)
                    """,
                    (account_id, strip_subject(members[0].subject)),
                ).lastrowid
            for member in members:
                previous = existing.get(member.message_id)
                conn.execute(
                    """
                    INSERT INTO messages(
                        thread_id, message_id, from_addr, to_addr, cc_addr, date, subject,
                        body_text, body_html, attachments, in_reply_to, references_hdr
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(message_id) DO UPDATE SET
                        thread_id = excluded.thread_id,
                        from_addr = excluded.from_addr,
                        to_addr = excluded.to_addr,
                        cc_addr = excluded.cc_addr,
                        date = excluded.date,
                        subject = excluded.subject,
                        body_text = excluded.body_text,
                        body_html = excluded.body_html,
                        attachments = excluded.attachments,
                        in_reply_to = excluded.in_reply_to,
                        references_hdr = excluded.references_hdr
                    """,
                    (
                        keeper,
                        member.message_id,
                        member.from_addr,
                        member.to_addr,
                        member.cc_addr,
                        member.date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        member.subject,
                        member.body_text,
                        member.body_html,
                        json.dumps(member.attachments, ensure_ascii=False),
                        member.in_reply_to,
                        member.references,
                    ),
                )
                saved = conn.execute(
                    "SELECT id, body_text FROM messages WHERE message_id = ?",
                    (member.message_id,),
                ).fetchone()
                changed = previous is None or (previous["body_text"] or "") != (member.body_text or "")
                if changed:
                    pending.append((keeper, saved["id"], member.body_text or member.subject or ""))
                existing[member.message_id] = {
                    "id": saved["id"],
                    "message_id": member.message_id,
                    "thread_id": keeper,
                    "body_text": member.body_text,
                }
            _refresh_thread(conn, keeper)
        thread_count = conn.execute(
            "SELECT COUNT(*) AS count FROM threads WHERE account_id = ?",
            (account_id,),
        ).fetchone()["count"]
        message_count = conn.execute(
            """
            SELECT COUNT(*) AS count FROM messages
            JOIN threads ON threads.id = messages.thread_id
            WHERE threads.account_id = ?
            """,
            (account_id,),
        ).fetchone()["count"]
    return thread_count, message_count, pending


def _ensure_account(conn, cfg: dict) -> int:
    email = cfg["imap_user"] or "mock@local"
    host = cfg["imap_host"] or "mock"
    user = cfg["imap_user"] or "mock"
    secret = encrypt_secret(cfg["imap_password"]) if cfg["imap_password"] else "env"
    row = conn.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
    if row:
        conn.execute(
            """
            UPDATE accounts
            SET email = ?, imap_host = ?, imap_port = ?, imap_user = ?, imap_password_enc = ?
            WHERE id = ?
            """,
            (email, host, int(cfg["imap_port"]), user, secret, row["id"]),
        )
        return row["id"]
    cursor = conn.execute(
        """
        INSERT INTO accounts(email, imap_host, imap_port, imap_user, imap_password_enc)
        VALUES(?, ?, ?, ?, ?)
        """,
        (email, host, int(cfg["imap_port"]), user, secret),
    )
    return int(cursor.lastrowid)


def _move_thread(conn, source: int, target: int) -> None:
    conn.execute("UPDATE messages SET thread_id = ? WHERE thread_id = ?", (target, source))
    conn.execute("UPDATE summaries SET thread_id = ? WHERE thread_id = ?", (target, source))
    conn.execute("UPDATE drafts SET thread_id = ? WHERE thread_id = ?", (target, source))
    conn.execute("UPDATE tasks SET thread_id = ? WHERE thread_id = ?", (target, source))
    conn.execute("DELETE FROM threads WHERE id = ?", (source,))


def _refresh_thread(conn, thread_id: int) -> None:
    rows = conn.execute(
        """
        SELECT from_addr, date, subject, body_text, body_html
        FROM messages WHERE thread_id = ? ORDER BY date, id
        """,
        (thread_id,),
    ).fetchall()
    if not rows:
        conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        return
    names: list[str] = []
    for row in rows:
        name = from_name(row["from_addr"])
        if name not in names:
            names.append(name)
    latest = rows[-1]
    conn.execute(
        """
        UPDATE threads
        SET subject = ?, participants = ?, last_message_at = ?
        WHERE id = ?
        """,
        (
            strip_subject(rows[0]["subject"]),
            ", ".join(names[:8]),
            latest["date"],
            thread_id,
        ),
    )
