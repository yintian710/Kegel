from __future__ import annotations

from decimal import Decimal
from typing import Any

import orjson
from fastapi.responses import Response


class ORJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, default=_default, option=orjson.OPT_NON_STR_KEYS)


def _default(value: Any):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} 无法序列化")


def _is_id_key(key: Any) -> bool:
    return isinstance(key, str) and (key == "id" or key.endswith("_id"))


def normalize(value: Any) -> Any:
    """Turn every integer id / *_id into a string so 64-bit snowflakes survive JS Number."""
    if isinstance(value, dict):
        return {key: (str(item) if _is_id_key(key) and type(item) is int else normalize(item))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def good(data: Any = None, status: int = 200) -> ORJSONResponse:
    return ORJSONResponse({"code": 0, "data": normalize(data), "msg": "success"}, status_code=status)


def bad(msg: str, code: int = 400) -> ORJSONResponse:
    return ORJSONResponse({"code": code, "data": None, "msg": msg}, status_code=code)
