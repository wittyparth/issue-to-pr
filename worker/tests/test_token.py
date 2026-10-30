from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from it2pr_worker.token import (
    InstallationToken,
    TokenMintError,
    build_app_jwt,
    get_installation_token,
    needs_remint,
)


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def test_build_app_jwt_is_decodable_rs256(rsa_keypair: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_keypair

    token = build_app_jwt("123456", private_pem)

    decoded = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == "123456"
    assert decoded["exp"] > decoded["iat"]


@dataclass
class _FakeResponse:
    status_code: int
    _body: dict

    def json(self) -> dict:
        return self._body


class _FakeHttpClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, *, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append((url, headers))
        return self.response


def test_get_installation_token_sends_bearer_jwt_to_correct_url(
    rsa_keypair: tuple[str, str],
) -> None:
    private_pem, _ = rsa_keypair
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake_http = _FakeHttpClient(
        _FakeResponse(status_code=201, _body={"token": "ghs_faketoken", "expires_at": expires_at})
    )

    result = get_installation_token(
        installation_id=99,
        app_id="123456",
        private_key_pem=private_pem,
        http=fake_http,
    )

    assert isinstance(result, InstallationToken)
    assert result.token == "ghs_faketoken"

    assert len(fake_http.calls) == 1
    url, headers = fake_http.calls[0]
    assert url == "https://api.github.com/app/installations/99/access_tokens"
    assert headers["Authorization"].startswith("Bearer ")

    sent_jwt = headers["Authorization"].removeprefix("Bearer ")
    decoded = jwt.decode(sent_jwt, options={"verify_signature": False})
    assert decoded["iss"] == "123456"


def test_get_installation_token_raises_on_http_error(rsa_keypair: tuple[str, str]) -> None:
    private_pem, _ = rsa_keypair
    fake_http = _FakeHttpClient(_FakeResponse(status_code=404, _body={}))

    with pytest.raises(TokenMintError):
        get_installation_token(
            installation_id=99,
            app_id="123456",
            private_key_pem=private_pem,
            http=fake_http,
        )


def test_needs_remint_true_near_expiry() -> None:
    now = datetime.now(UTC)
    token = InstallationToken(token="ghs_x", expires_at=now + timedelta(seconds=100))

    assert needs_remint(token, now, margin_seconds=300) is True


def test_needs_remint_false_when_fresh() -> None:
    now = datetime.now(UTC)
    token = InstallationToken(token="ghs_x", expires_at=now + timedelta(hours=1))

    assert needs_remint(token, now, margin_seconds=300) is False


def test_needs_remint_handles_naive_now() -> None:
    # A naive `now` must be treated as UTC, not raise TypeError against the
    # tz-aware expires_at.
    aware_now = datetime.now(UTC)
    naive_now = aware_now.replace(tzinfo=None)
    near = InstallationToken(token="ghs_x", expires_at=aware_now + timedelta(seconds=100))
    fresh = InstallationToken(token="ghs_x", expires_at=aware_now + timedelta(hours=1))

    assert needs_remint(near, naive_now, margin_seconds=300) is True
    assert needs_remint(fresh, naive_now, margin_seconds=300) is False
