"""Worker credential contract (M7 integration follow-up).

Resolves the GitHub App id + private key PEM from AWS SSM Parameter Store via
an injectable `boto3` client, so tests never touch real AWS. The dispatcher
(`app/src/lib/ecs.ts`) passes the `githubApp` parameter name (metadata only,
never the value) via `GITHUB_APP_PARAM_NAME`; `__main__.py` reads it here.

Parameter JSON shape: `{"app_id": "...", "private_key_pem": "..."}`.

These are plain `String` SSM parameters, not `SecureString` (CloudFormation
cannot create SecureString parameters — see infra/lib/data.ts), swapped from
Secrets Manager to avoid its flat $0.40/secret/month fee. `WithDecryption`
is harmless for a non-encrypted String parameter.

Never log the resolved credentials; error messages deliberately omit secret
values (only the parameter name and missing-field names are surfaced).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class SecretsError(RuntimeError):
    """Raised when the GitHub App parameter cannot be fetched or parsed."""


class SsmClient(Protocol):
    def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, Any]: ...  # noqa: N803


@dataclass(frozen=True, slots=True)
class GithubAppCreds:
    app_id: str
    private_key_pem: str


def _get_parameter_value(param_name: str, client: SsmClient) -> str:
    try:
        response = client.get_parameter(Name=param_name, WithDecryption=True)
    except Exception as exc:  # noqa: BLE001 - re-raise without leaking secret material
        raise SecretsError(f"Failed to fetch parameter {param_name!r}: {type(exc).__name__}") from exc

    value = response.get("Parameter", {}).get("Value")
    if value is None:
        raise SecretsError(f"Parameter {param_name!r} has no value")
    return value


def fetch_github_app_credentials(
    param_name: str, *, client: SsmClient | None = None
) -> GithubAppCreds:
    """Fetch and parse the `githubApp` parameter from SSM Parameter Store.

    `client` should be an injected fake/mock in tests (no real AWS call). In
    production it defaults to a real `boto3` SSM client.
    """
    resolved_client = client if client is not None else _default_client()
    raw = _get_parameter_value(param_name, resolved_client)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecretsError(f"Parameter {param_name!r} is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise SecretsError(f"Parameter {param_name!r} JSON must be an object")

    app_id = parsed.get("app_id")
    private_key_pem = parsed.get("private_key_pem")
    missing = [
        name
        for name, value in (("app_id", app_id), ("private_key_pem", private_key_pem))
        if not isinstance(value, str) or not value
    ]
    if missing:
        raise SecretsError(
            f"Parameter {param_name!r} is missing required field(s): {', '.join(missing)}"
        )

    return GithubAppCreds(app_id=app_id, private_key_pem=private_key_pem)


def fetch_llm_provider_keys(param_name: str, *, client: SsmClient | None = None) -> dict[str, str]:
    """Fetch and parse the `it2pr/llm-providers` parameter from SSM Parameter Store.

    Parameter JSON shape is a flat object mapping provider env var names to
    their key values, e.g. `{"OPENROUTER_API_KEY": "...", "OPENAI_API_KEY":
    "..."}`. `client` should be an injected fake/mock in tests (no real AWS
    call). Never log the resolved values.
    """
    resolved_client = client if client is not None else _default_client()
    raw = _get_parameter_value(param_name, resolved_client)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecretsError(f"Parameter {param_name!r} is not valid JSON") from exc

    if not isinstance(parsed, dict):
        raise SecretsError(f"Parameter {param_name!r} JSON must be an object")

    invalid = [name for name, value in parsed.items() if not isinstance(value, str) or not value]
    if invalid:
        raise SecretsError(
            f"Parameter {param_name!r} has non-string or empty value(s) for: {', '.join(invalid)}"
        )

    return dict(parsed)


def _default_client() -> SsmClient:
    import boto3

    return boto3.client("ssm")


__all__ = [
    "GithubAppCreds",
    "SecretsError",
    "fetch_github_app_credentials",
    "fetch_llm_provider_keys",
]
