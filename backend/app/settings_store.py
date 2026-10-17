import json

from app.config import settings
from app.crypto import decrypt_secret, encrypt_secret
from app.db import db
from app.errors import AppError

ALLOWED_TONES = ("деловой", "нейтральный", "дружелюбный")


def _read_map() -> dict[str, str]:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] or "" for row in rows}


def _write(key: str, value: str | None) -> None:
    with db() as conn:
        if value is None:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def effective() -> dict:
    stored = _read_map()

    def pick(key: str, default: str) -> str:
        if key in stored and stored[key] != "":
            return stored[key]
        return default

    password = ""
    if stored.get("imap_password_enc"):
        password = decrypt_secret(stored["imap_password_enc"])
    if not password:
        password = settings.imap_password

    return {
        "imap_mode": pick("imap_mode", settings.imap_mode or "mock"),
        "imap_host": pick("imap_host", settings.imap_host),
        "imap_port": int(pick("imap_port", str(settings.imap_port))),
        "imap_ssl": pick("imap_ssl", "true" if settings.imap_ssl else "false") == "true",
        "imap_user": pick("imap_user", settings.imap_user),
        "imap_password": password,
        "model_name": pick("model_name", settings.model_name),
        "sync_days": int(pick("sync_days", str(settings.sync_days))),
        "digest_hours": int(pick("digest_hours", str(settings.digest_hours))),
    }


def public_settings() -> dict:
    current = effective()
    current.pop("imap_password")
    current["imap_password_set"] = bool(effective()["imap_password"])
    return current


def validate_settings(payload: dict, require_host: bool) -> dict:
    errors: list[str] = []
    mode = str(payload.get("imap_mode") or "mock").strip().lower()
    if mode not in ("mock", "imap"):
        errors.append("imap_mode")
        mode = "mock"
    host = str(payload.get("imap_host") or "").strip()
    if require_host and mode == "imap" and not host:
        errors.append("imap_host")
    try:
        port = int(payload.get("imap_port"))
        if port < 1 or port > 65535:
            errors.append("imap_port")
    except (TypeError, ValueError):
        port = 0
        errors.append("imap_port")
    try:
        sync_days = int(payload.get("sync_days"))
        if sync_days < 1 or sync_days > 365:
            errors.append("sync_days")
    except (TypeError, ValueError):
        sync_days = 0
        errors.append("sync_days")
    try:
        digest_hours = int(payload.get("digest_hours"))
        if digest_hours < 1 or digest_hours > 168:
            errors.append("digest_hours")
    except (TypeError, ValueError):
        digest_hours = 0
        errors.append("digest_hours")
    if errors:
        raise AppError(
            "VALIDATION_ERROR",
            "Проверьте отмеченные поля",
            422,
            {"fields": errors},
        )
    return {
        "imap_mode": mode,
        "imap_host": host,
        "imap_port": port,
        "imap_ssl": bool(payload.get("imap_ssl")),
        "imap_user": str(payload.get("imap_user") or "").strip(),
        "model_name": str(payload.get("model_name") or settings.model_name).strip() or settings.model_name,
        "sync_days": sync_days,
        "digest_hours": digest_hours,
    }


def save_settings(payload: dict) -> dict:
    cleaned = validate_settings(payload, require_host=True)
    _write("imap_mode", cleaned["imap_mode"])
    _write("imap_host", cleaned["imap_host"])
    _write("imap_port", str(cleaned["imap_port"]))
    _write("imap_ssl", "true" if cleaned["imap_ssl"] else "false")
    _write("imap_user", cleaned["imap_user"])
    _write("model_name", cleaned["model_name"])
    _write("sync_days", str(cleaned["sync_days"]))
    _write("digest_hours", str(cleaned["digest_hours"]))
    if "imap_password" in payload and payload["imap_password"] is not None:
        password = str(payload["imap_password"])
        if password.strip():
            _write("imap_password_enc", encrypt_secret(password))
        else:
            _write("imap_password_enc", None)
    return public_settings()


def get_json_setting(key: str):
    stored = _read_map()
    raw = stored.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json_setting(key: str, value) -> None:
    _write(key, json.dumps(value, ensure_ascii=False))
