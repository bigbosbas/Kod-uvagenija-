import json
import os
import re
import threading
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
INBOX_DIR = os.path.join(BASE, "inbox")
FILES_DIR = os.path.join(INBOX_DIR, "files")
JSONL = os.path.join(INBOX_DIR, "messages.jsonl")
DIGEST = os.path.join(INBOX_DIR, "digest.md")
STATE = os.path.join(INBOX_DIR, "state.json")

MAX_DOWNLOAD = 20 * 1024 * 1024

_lock = threading.Lock()


def ensure_dirs():
    os.makedirs(FILES_DIR, exist_ok=True)


def is_on():
    try:
        with open(STATE, encoding="utf-8") as f:
            return bool(json.load(f).get("on"))
    except (OSError, ValueError):
        return False


def set_on(value):
    ensure_dirs()
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"on": bool(value)}, f)


def _files_of(message):
    out = []
    ct = message.content_type

    if ct == "photo" and message.photo:
        big = max(message.photo, key=lambda p: p.file_size or 0)
        out.append({"kind": "photo", "file_id": big.file_id,
                    "file_unique_id": big.file_unique_id,
                    "file_size": big.file_size,
                    "file_name": None,
                    "meta": f"{big.width}x{big.height}"})
    for attr, kind in (("video", "video"), ("document", "document"), ("audio", "audio"),
                       ("voice", "voice"), ("animation", "animation"),
                       ("video_note", "video_note"), ("sticker", "sticker")):
        obj = getattr(message, attr, None)
        if obj:
            out.append({"kind": kind, "file_id": obj.file_id,
                        "file_unique_id": obj.file_unique_id,
                        "file_size": getattr(obj, "file_size", None),
                        "file_name": getattr(obj, "file_name", None),
                        "meta": getattr(obj, "mime_type", None) or getattr(obj, "emoji", None)})
    return out


def _utf16_slice(text, offset, length):
    b = (text or "").encode("utf-16-le")
    return b[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="replace")


def _custom_emoji(message):
    found = []
    for ents, src in ((message.entities, message.text),
                      (message.caption_entities, message.caption)):
        for e in ents or []:
            if e.type == "custom_emoji":
                found.append({
                    "custom_emoji_id": e.custom_emoji_id,
                    "emoji": _utf16_slice(src, e.offset, e.length),
                })
    return found


def _html(message, kind):
    try:
        return message.html_text if kind == "text" else message.html_caption
    except Exception as e:
        return (message.text if kind == "text" else message.caption)


def _raw(message):
    raw = message.json
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _origin(message):
    return _raw(message).get("forward_origin")


def _safe_name(name, fallback):
    name = re.sub(r"[^\w.\-]+", "_", name or "").strip("_")
    return name[:80] or fallback


def count():
    if not os.path.exists(JSONL):
        return 0
    with open(JSONL, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def save(message, downloader=None):
    ensure_dirs()
    with _lock:
        n = count() + 1
        files = _files_of(message)

        for i, f in enumerate(files):
            size = f.get("file_size") or 0
            if not downloader or size > MAX_DOWNLOAD:
                f["saved_as"] = None
                f["skip_reason"] = "больше 20 МБ — только file_id" if size > MAX_DOWNLOAD else None
                continue
            try:
                data, tg_path = downloader(f["file_id"])
                ext = os.path.splitext(tg_path or "")[1] or ""
                base = _safe_name(f.get("file_name"), f"{f['kind']}{ext}")
                if not os.path.splitext(base)[1]:
                    base += ext
                fname = f"{n:04d}_{i}_{base}"
                with open(os.path.join(FILES_DIR, fname), "wb") as fh:
                    fh.write(data)
                f["saved_as"] = f"files/{fname}"
                f["skip_reason"] = None
            except Exception as e:
                f["saved_as"] = None
                f["skip_reason"] = f"ошибка скачивания: {e}"

        rec = {
            "n": n,
            "received_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "message_id": message.message_id,
            "content_type": message.content_type,
            "media_group_id": getattr(message, "media_group_id", None),
            "text": message.text,
            "html": _html(message, "text") if message.text else None,
            "caption": message.caption,
            "caption_html": _html(message, "caption") if message.caption else None,
            "custom_emoji": _custom_emoji(message),
            "forward_origin": _origin(message),
            "files": files,
            "raw": _raw(message),
        }
        with open(JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_all():
    if not os.path.exists(JSONL):
        return []
    out = []
    with open(JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def summary():
    recs = load_all()
    by_type, emoji, downloaded, only_id = {}, set(), 0, 0
    for r in recs:
        by_type[r["content_type"]] = by_type.get(r["content_type"], 0) + 1
        for e in r["custom_emoji"]:
            emoji.add(e["custom_emoji_id"])
        for f in r["files"]:
            if f.get("saved_as"):
                downloaded += 1
            else:
                only_id += 1
    return {"total": len(recs), "by_type": by_type, "custom_emoji": len(emoji),
            "downloaded": downloaded, "only_id": only_id}


def build_digest():
    recs = load_all()
    s = summary()
    lines = [
        "# Приёмник — собранные материалы",
        "",
        f"Всего сообщений: **{s['total']}**  ",
        f"По типам: {', '.join(f'{k} — {v}' for k, v in sorted(s['by_type'].items())) or '—'}  ",
        f"Уникальных премиум-эмодзи: {s['custom_emoji']}  ",
        f"Файлов скачано: {s['downloaded']}, только file_id: {s['only_id']}",
        "",
        "Тексты приведены в HTML-виде — в таком виде их можно класть прямо в `content.py`.",
        "",
        "---",
        "",
    ]
    for r in recs:
        lines.append(f"## {r['n']}. {r['content_type']}  ·  {r['received_at']}")
        if r.get("media_group_id"):
            lines.append(f"_альбом: {r['media_group_id']}_")
        if r.get("forward_origin"):
            o = r["forward_origin"]
            who = (o.get("sender_user", {}).get("first_name")
                   or o.get("chat", {}).get("title")
                   or o.get("sender_user_name") or o.get("type"))
            lines.append(f"_переслано из: {who}_")
        body = r.get("html") or r.get("caption_html") or r.get("text") or r.get("caption")
        if body:
            lines += ["", "```html", body, "```"]
        for e in r["custom_emoji"]:
            lines.append(f"- премиум-эмодзи `{e['emoji']}` → id `{e['custom_emoji_id']}`")
        for f in r["files"]:
            note = f.get("saved_as") or f.get("skip_reason") or "не скачан"
            size = f.get("file_size")
            size_s = f"{size/1024/1024:.1f} МБ" if size else "размер неизвестен"
            lines.append(f"- **{f['kind']}** · {size_s} · `{f['file_id']}` · {note}")
        lines += ["", "---", ""]

    ensure_dirs()
    with open(DIGEST, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return DIGEST, s
