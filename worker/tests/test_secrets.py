from __future__ import annotations

import json
from typing import Any

import pytest

from it2pr_worker.secrets import (
    GithubAppCreds,
    SecretsError,
    fetch_github_app_credentials,
    fetch_llm_provider_keys,
)

PARAM_NAME = "/it2pr/github-app"
LLM_PARAM_NAME = "/it2pr/llm-providers"


class FakeSsmClient:
    def __init__(self, value: str | None = None, *, raise_error: bool = False) -> None:
        self._value = value
        self._raise_error = raise_error
        self.calls: list[str] = []

    def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, Any]:  # noqa: N803
        self.calls.append(Name)
        if self._raise_error:
            raise RuntimeError("AccessDeniedException: no permission")
        if self._value is None:
            return {"Parameter": {}}
        return {"Parameter": {"Value": self._value}}


def test_fetch_parses_app_id_and_pem() -> None:
    pem = "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    payload = json.dumps({"app_id": "123456", "private_key_pem": pem})
    client = FakeSsmClient(value=payload)

    creds = fetch_github_app_credentials(PARAM_NAME, client=client)

    assert creds == GithubAppCreds(app_id="123456", private_key_pem=pem)
    assert client.calls == [PARAM_NAME]


def test_fetch_raises_on_missing_parameter_value() -> None:
    client = FakeSsmClient(value=None)

    with pytest.raises(SecretsError, match="no value"):
        fetch_github_app_credentials(PARAM_NAME, client=client)


def test_fetch_raises_on_malformed_json() -> None:
    client = FakeSsmClient(value="not json{{{")

    with pytest.raises(SecretsError, match="not valid JSON"):
        fetch_github_app_credentials(PARAM_NAME, client=client)


def test_fetch_raises_on_missing_fields() -> None:
    client = FakeSsmClient(value=json.dumps({"app_id": "123"}))

    with pytest.raises(SecretsError, match="private_key_pem"):
        fetch_github_app_credentials(PARAM_NAME, client=client)


def test_fetch_raises_clear_error_without_leaking_creds_on_client_failure() -> None:
    client = FakeSsmClient(raise_error=True)

    with pytest.raises(SecretsError) as exc_info:
        fetch_github_app_credentials(PARAM_NAME, client=client)

    assert "AccessDeniedException" not in str(exc_info.value)
    assert "no permission" not in str(exc_info.value)


def test_error_messages_never_contain_secret_values() -> None:
    secret_pem = "-----BEGIN PRIVATE KEY-----\nSUPER-SECRET-PEM-DATA\n-----END PRIVATE KEY-----"
    client = FakeSsmClient(value=json.dumps({"app_id": ""}))

    with pytest.raises(SecretsError) as exc_info:
        fetch_github_app_credentials(PARAM_NAME, client=client)

    assert secret_pem not in str(exc_info.value)


def test_fetch_llm_provider_keys_parses_json_object() -> None:
    payload = json.dumps({"OPENROUTER_API_KEY": "or-key-123", "OPENAI_API_KEY": "oa-key-456"})
    client = FakeSsmClient(value=payload)

    keys = fetch_llm_provider_keys(LLM_PARAM_NAME, client=client)

    assert keys == {"OPENROUTER_API_KEY": "or-key-123", "OPENAI_API_KEY": "oa-key-456"}
    assert client.calls == [LLM_PARAM_NAME]


def test_fetch_llm_provider_keys_raises_on_missing_parameter_value() -> None:
    client = FakeSsmClient(value=None)

    with pytest.raises(SecretsError, match="no value"):
        fetch_llm_provider_keys(LLM_PARAM_NAME, client=client)


def test_fetch_llm_provider_keys_raises_on_malformed_json() -> None:
    client = FakeSsmClient(value="not json{{{")

    with pytest.raises(SecretsError, match="not valid JSON"):
        fetch_llm_provider_keys(LLM_PARAM_NAME, client=client)


def test_fetch_llm_provider_keys_raises_on_non_object_json() -> None:
    client = FakeSsmClient(value=json.dumps(["not", "an", "object"]))

    with pytest.raises(SecretsError, match="must be an object"):
        fetch_llm_provider_keys(LLM_PARAM_NAME, client=client)


def test_fetch_llm_provider_keys_raises_on_empty_or_non_string_values() -> None:
    client = FakeSsmClient(
        value=json.dumps({"OPENROUTER_API_KEY": "", "OPENAI_API_KEY": 123})
    )

    with pytest.raises(SecretsError, match="OPENROUTER_API_KEY"):
        fetch_llm_provider_keys(LLM_PARAM_NAME, client=client)


def test_fetch_llm_provider_keys_error_never_leaks_client_exception_detail() -> None:
    client = FakeSsmClient(raise_error=True)

    with pytest.raises(SecretsError) as exc_info:
        fetch_llm_provider_keys(LLM_PARAM_NAME, client=client)

    assert "AccessDeniedException" not in str(exc_info.value)
    assert "no permission" not in str(exc_info.value)
