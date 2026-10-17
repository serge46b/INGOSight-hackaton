import sqlite3
import threading
from contextlib import contextmanager

from app.config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    imap_host TEXT NOT NULL,
    imap_port INTEGER NOT NULL,
    imap_user TEXT NOT NULL,
    imap_password_enc TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    subject TEXT,
    participants TEXT,
    last_message_at DATETIME,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    message_id TEXT UNIQUE,
    from_addr TEXT,
    to_addr TEXT,
    cc_addr TEXT,
    date DATETIME,
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    attachments TEXT,
    in_reply_to TEXT,
    references_hdr TEXT,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    summary_text TEXT,
    source_hash TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    draft_text TEXT,
    source_hash TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    message_id INTEGER,
    thread_id INTEGER,
    text TEXT NOT NULL,
    due_date DATE,
    is_done BOOLEAN DEFAULT 0,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
"""


def _connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(settings.database_path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def db():
    conn = _connection()
    with _lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def reset_connection() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
