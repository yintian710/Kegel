from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from app.common.payment_log import payment_log

_BODY_LIMIT = 1_000_000
_AUDIT_PREFIXES = ("/lpay/", "/epay/")


async def json_request(url: str, *, method: str = "GET", data: dict | None = None,
                       headers: dict | None = None, form: bool = False, timeout: float = 10) -> dict[str, Any]:
    """Call a remote JSON API. Payment-gateway exchanges are written to the payment log untruncated."""
    request_headers = dict(headers or {})
    body: bytes | None = None
    if data is not None:
        body = urlencode(data).encode() if form else json.dumps(data).encode()
        request_headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    exchange_id = secrets.token_hex(12)
    audit = urlsplit(url).path.startswith(_AUDIT_PREFIXES)
    if audit:
        payment_log("outbound.request", exchange_id=exchange_id, method=method, url=url,
                    headers=request_headers, body=body.decode("utf-8", errors="replace") if body else "")
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream(method, url, content=body, headers=request_headers) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if not audit and len(raw) > _BODY_LIMIT:
                        break
        if audit:
            payment_log("outbound.response", exchange_id=exchange_id, status=response.status_code,
                        headers={key: response.headers.get_list(key) for key in response.headers.keys()},
                        body=bytes(raw).decode("utf-8", errors="replace"))
        response.raise_for_status()
        result = json.loads(bytes(raw))
        if not isinstance(result, dict):
            raise ValueError("远端响应不是 JSON 对象")
        return result
    except Exception as exc:
        if audit and not isinstance(exc, httpx.HTTPStatusError):
            payment_log("outbound.error", exchange_id=exchange_id, error_type=type(exc).__name__, error=str(exc))
        raise
