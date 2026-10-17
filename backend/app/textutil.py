import re
from dataclasses import dataclass

_SUBJECT_PREFIX = re.compile(
    r"^(?:re|fw|fwd|aw|ответ|пересл\.?|на)(?:\s*\[\d+\])?\s*:\s*",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"^(?:конечно|вот саммари|вот черновик|вот ответ)\s*[:!—.\-]*\s*",
    re.IGNORECASE,
)


def strip_subject(subject: str) -> str:
    text = (subject or "").strip()
    previous = None
    while previous != text:
        previous = text
        text = _SUBJECT_PREFIX.sub("", text).strip()
    return text or (subject or "").strip() or "(без темы)"


def normalize_subject(subject: str) -> str:
    stripped = strip_subject(subject)
    if stripped == "(без темы)":
        return ""
    return stripped.casefold()


def norm_message_id(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("<") and text.endswith(">"):
        return text[1:-1].strip()
    return text


def reference_ids(in_reply_to: str, references: str) -> list[str]:
    found: list[str] = []
    blob = f"{in_reply_to or ''} {references or ''}"
    for token in re.findall(r"<[^>]+>|[\w.@+\-]+", blob):
        mid = norm_message_id(token)
        if mid and "@" in mid:
            found.append(mid)
    return found


@dataclass
class MailLink:
    message_id: str
    in_reply_to: str
    references: str
    subject: str


def group_indices(messages: list[MailLink]) -> list[list[int]]:
    count = len(messages)
    parent = list(range(count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    by_id: dict[str, int] = {}
    for index, message in enumerate(messages):
        mid = norm_message_id(message.message_id)
        if mid:
            by_id[mid] = index

    for index, message in enumerate(messages):
        for ref in reference_ids(message.in_reply_to, message.references):
            other = by_id.get(ref)
            if other is not None:
                union(index, other)

    by_subject: dict[str, int] = {}
    for index, message in enumerate(messages):
        key = normalize_subject(message.subject)
        if not key:
            continue
        if key in by_subject:
            union(index, by_subject[key])
        else:
            by_subject[key] = index

    clusters: dict[int, list[int]] = {}
    for index in range(count):
        clusters.setdefault(find(index), []).append(index)
    return list(clusters.values())


def chunk_text(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    if size < 1:
        size = 1
    step = max(1, size - max(0, overlap))
    chunks: list[str] = []
    index = 0
    while index < len(words):
        chunks.append(" ".join(words[index : index + size]))
        if index + size >= len(words):
            break
        index += step
    return chunks


def postprocess(text: str, limit: int = 8000) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _BOILERPLATE.sub("", cleaned).strip()
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    cleaned = _typographic(cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…\nОтвет сокращён"
    return cleaned


def _typographic(text: str) -> str:
    text = text.replace("--", "—")
    lines = []
    for line in text.split("\n"):
        if re.match(r"\s*[-•]\s+", line):
            lines.append(line)
        else:
            lines.append(re.sub(r"\s+-\s+", " — ", line))
    text = "\n".join(lines)
    open_quote = True
    chars: list[str] = []
    for char in text:
        if char == '"':
            chars.append("«" if open_quote else "»")
            open_quote = not open_quote
        else:
            chars.append(char)
    return "".join(chars)


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def preview(text: str, limit: int = 140) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def from_name(value: str) -> str:
    text = (value or "").strip()
    if "<" in text:
        text = text.split("<", 1)[0].strip().strip('"')
    return text or (value or "").strip() or "—"


def plural(count: int, one: str, few: str, many: str) -> str:
    number = abs(count) % 100
    tail = number % 10
    if 11 <= number <= 19:
        word = many
    elif tail == 1:
        word = one
    elif 2 <= tail <= 4:
        word = few
    else:
        word = many
    return f"{count} {word}"
