import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from app.textutil import html_to_text, norm_message_id


@dataclass
class RawMessage:
    message_id: str
    from_addr: str
    to_addr: str
    cc_addr: str
    date: datetime
    subject: str
    body_text: str
    body_html: str
    attachments: list[str]
    in_reply_to: str
    references: str


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _part_text(part) -> str:
    try:
        content = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        content = payload.decode(charset, errors="replace")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content)


def parse_raw_email(raw: bytes, now: datetime | None = None) -> RawMessage:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            disposition = part.get_content_disposition() or ""
            if filename and disposition == "attachment":
                attachments.append(_decode_header(filename))
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                text_parts.append(_part_text(part))
            elif content_type == "text/html":
                html_parts.append(_part_text(part))
    else:
        content_type = message.get_content_type()
        body = _part_text(message)
        if content_type == "text/html":
            html_parts.append(body)
        else:
            text_parts.append(body)

    body_text = "\n".join(part.strip() for part in text_parts if part.strip())[:1_000_000]
    body_html = "\n".join(html_parts)[:1_000_000]
    if not body_text and body_html:
        body_text = html_to_text(body_html)[:1_000_000]

    age = message.get("X-Fixture-Age-Hours")
    if age:
        moment = now or datetime.now(timezone.utc)
        date = moment - timedelta(hours=float(age))
    else:
        try:
            date = parsedate_to_datetime(message.get("Date"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            date = date.astimezone(timezone.utc)
        except Exception:
            date = now or datetime.now(timezone.utc)

    message_id = norm_message_id(_decode_header(message.get("Message-ID")))
    if not message_id:
        message_id = f"generated-{abs(hash(raw))}"

    return RawMessage(
        message_id=message_id,
        from_addr=_decode_header(message.get("From")),
        to_addr=_decode_header(message.get("To")),
        cc_addr=_decode_header(message.get("Cc")),
        date=date,
        subject=_decode_header(message.get("Subject")),
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
        in_reply_to=norm_message_id(_decode_header(message.get("In-Reply-To"))),
        references=_decode_header(message.get("References")),
    )


def load_mock_messages(folder: str, sync_days: int, now: datetime | None = None) -> list[RawMessage]:
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=sync_days)
    messages: list[RawMessage] = []
    if not os.path.isdir(folder):
        return messages
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".eml"):
            continue
        path = os.path.join(folder, name)
        with open(path, "rb") as handle:
            raw = handle.read()
        parsed = parse_raw_email(raw, now=moment)
        if parsed.date >= cutoff:
            messages.append(parsed)
        if len(messages) >= 5000:
            break
    return messages


def load_imap_messages(
    host: str,
    port: int,
    use_ssl: bool,
    user: str,
    password: str,
    sync_days: int,
) -> list[RawMessage]:
    import imaplib

    imaplib.Debug = 0
    password = (password or "").replace(" ", "")
    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        client.login(user, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise OSError("INBOX unavailable")
        since = (datetime.now(timezone.utc) - timedelta(days=sync_days)).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since)
        if status != "OK" or not data or not data[0]:
            return []
        numbers = data[0].split()[-5000:]
        messages: list[RawMessage] = []
        for number in numbers:
            status, fetched = client.fetch(number, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            messages.append(parse_raw_email(fetched[0][1]))
        return messages
    finally:
        try:
            client.logout()
        except Exception:
            pass


def probe_imap(host: str, port: int, use_ssl: bool, user: str, password: str) -> None:
    import imaplib

    imaplib.Debug = 0
    password = (password or "").replace(" ", "")
    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        client.login(user, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise OSError("INBOX unavailable")
    finally:
        try:
            client.logout()
        except Exception:
            pass
