"""GitHub App JWT + installation-token minting.

The worker mints its own short-lived installation token at start from the
App private key (Principle 1: security by construction). Never log the JWT,
the private key PEM, or the installation token.

`http` and `now` are injectable so tests never touch the network or rely on
wall-clock time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
import jwt

_JWT_TTL_SECONDS = 9 * 60  # ~9 minutes; GitHub caps App JWTs at 10 minutes.
_GITHUB_API_BASE = "https://api.github.com"


class TokenMintError(RuntimeError):
    """Raised when the GitHub App JWT or installation token cannot be minted."""


class HttpPost(Protocol):
    def post(self, url: str, *, headers: dict[str, str]) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class InstallationToken:
    token: str
    expires_at: datetime


def build_app_jwt(
    app_id: str,
    private_key_pem: str,
    *,
    now: Callable[[], datetime] | None = None,
) -> str:
    """Build a short-lived RS256 App JWT (iss=app_id) per GitHub App auth docs."""
    current = (now or _utcnow)()
    payload: dict[str, Any] = {
        "iat": int(current.timestamp()) - 60,  # allow for clock drift
        "exp": int(current.timestamp()) + _JWT_TTL_SECONDS,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def get_installation_token(
    installation_id: int,
    app_id: str,
    private_key_pem: str,
    *,
    http: HttpPost | None = None,
    now: Callable[[], datetime] | None = None,
) -> InstallationToken:
    """Mint an installation access token by POSTing the App JWT to GitHub.

    `http` defaults to a fresh `httpx.Client()` but should be an injected
    fake/mock in tests so no real network call is made.
    """
    current = (now or _utcnow)()
    app_jwt = build_app_jwt(app_id, private_key_pem, now=lambda: current)
    client = http if http is not None else httpx.Client()

    url = f"{_GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = client.post(url, headers=headers)
    if response.status_code >= 400:
        raise TokenMintError(
            f"Failed to mint installation token: HTTP {response.status_code}"
        )

    body = response.json()
    try:
        token = body["token"]
        expires_at_raw = body["expires_at"]
    except KeyError as exc:
        raise TokenMintError("Installation token response missing expected fields") from exc

    expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
    return InstallationToken(token=token, expires_at=expires_at)


def needs_remint(
    token: InstallationToken,
    now: datetime,
    margin_seconds: int = 300,
) -> bool:
    """True if `token` expires within `margin_seconds` of `now` (default 5 min).

    `now` may be naive; a naive value is treated as UTC so the subtraction
    against the tz-aware `expires_at` never raises a TypeError.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return token.expires_at - now <= timedelta(seconds=margin_seconds)


def _utcnow() -> datetime:
    return datetime.now(UTC)
