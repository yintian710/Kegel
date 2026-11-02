from __future__ import annotations


class APIError(Exception):
    """Business failure carrying the HTTP status that views return via bad()."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
