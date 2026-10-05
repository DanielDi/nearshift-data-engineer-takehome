"""Explicit public-origin and demo-access policy for TLS-terminated hosting."""
from __future__ import annotations

import base64
import binascii
import hmac
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HostingPolicy:
    origin: str | None = None
    username: str = "reviewer"
    password: str = ""

    def __post_init__(self):
        if self.origin:
            parsed = urlsplit(self.origin)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path or parsed.query or parsed.fragment):
                raise ValueError("The public URL must be an HTTPS origin without a path or credentials.")
            if len(self.password) < 16 or not self.username or ':' in self.username:
                raise ValueError("Hosted access requires a username and a password of at least 16 characters.")

    @classmethod
    def from_environment(cls):
        origin = os.environ.get("APP_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
        if os.environ.get("RENDER") == "true" and not origin:
            raise ValueError("Render must provide its public HTTPS URL.")
        return cls(origin.rstrip('/') if origin else None,
                   os.environ.get("DEMO_USERNAME", "reviewer"),
                   os.environ.get("DEMO_PASSWORD", ""))

    def request_allowed(self, headers, local_port: int, *, write: bool) -> bool:
        origin = self.origin or f"http://127.0.0.1:{local_port}"
        if headers.get("Host") != urlsplit(origin).netloc:
            return False
        if self.origin and headers.get("X-Forwarded-Proto") != "https":
            return False
        # Public POSTs require an explicit same-origin browser request.
        return not write or headers.get("Origin") in ((origin,) if self.origin else (None, origin))

    def authenticated(self, authorization: str | None) -> bool:
        if not self.origin:
            return True
        try:
            scheme, encoded = (authorization or "").split(' ', 1)
            if scheme.lower() != "basic":
                return False
            supplied = base64.b64decode(encoded, validate=True).decode('utf-8')
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return False
        expected = f"{self.username}:{self.password}"
        return hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))
