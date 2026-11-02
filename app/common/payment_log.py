from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import Settings

_LOCK = threading.Lock()
_SECRET_FIELDS = {
    "authorization", "proxy-authorization", "cookie", "set-cookie", "sign", "key",
    "client_secret", "access_token", "refresh_token", "id_token", "secret", "token",
    "x-admin-token", "x-trigger-token", "x-secondary-password", "x-secondary-secret",
    "secondary_secret", "secondary_password",
}
_FIELD_PATTERN = "|".join(re.escape(key) for key in _SECRET_FIELDS)
_ASSIGNMENT = re.compile(
    rf'''(?i)((?<![\w-])["']?(?:{_FIELD_PATTERN})["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^&\s,}}]+)''')


def redact(value):
    """Mask credentials/signatures in nested structures, query strings and configured secrets."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if str(key).lower() in _SECRET_FIELDS else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(redact(json.loads(value)), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        if "?" in value and (value.startswith("/") or value.startswith(("http://", "https://"))):
            try:
                parsed = urlsplit(value)
                query = [(key, "[REDACTED]" if key.lower() in _SECRET_FIELDS else redact(item))
                         for key, item in parse_qsl(parsed.query, keep_blank_values=True)]
                value = urlunsplit(parsed._replace(query=urlencode(query)))
            except ValueError:
                pass
        value = _ASSIGNMENT.sub(lambda match: match[1] + '"[REDACTED]"', value)
        value = re.sub(r"(https?://)[^/@\s]+@", r"\1[REDACTED]@", value)
        for secret in Settings.secret_values():
            value = value.replace(secret, "[REDACTED]")
    return value


def payment_log(event: str, **details) -> None:
    """Append independently of business transactions; logging failures never undo a transfer."""
    record = {"time": datetime.now(Settings.SITE_TZ).isoformat(), "event": event, **redact(details)}
    line = json.dumps(record, ensure_ascii=False) + "\n"
    path = Path(Settings.PAYMENT_LOG_PATH)
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8", errors="backslashreplace") as stream:
                stream.write(line)
    except OSError as exc:
        print(f"支付日志写入失败 ({type(exc).__name__})，转存标准错误：{line}", file=sys.stderr, flush=True)
