from __future__ import annotations

from it2pr_worker.scrub import scrub, scrub_secrets_from


def test_scrub_redacts_github_installation_token() -> None:
    text = "using token ghs_1234567890abcdefGHIJ for auth"
    result = scrub(text)
    assert "ghs_1234567890abcdefGHIJ" not in result
    assert "***REDACTED***" in result


def test_scrub_redacts_github_pat_and_fine_grained() -> None:
    text = "ghp_abcdefghij1234567890 and github_pat_11ABCDEFG0abcdefghijklmno"
    result = scrub(text)
    assert "ghp_abcdefghij1234567890" not in result
    assert "github_pat_11ABCDEFG0abcdefghijklmno" not in result


def test_scrub_redacts_authorization_bearer_header() -> None:
    text = 'Authorization: Bearer sekrit-value-here-1234\nother line'
    result = scrub(text)
    assert "sekrit-value-here-1234" not in result
    assert "Authorization: Bearer ***REDACTED***" in result
    assert "other line" in result


def test_scrub_redacts_authorization_token_header() -> None:
    text = "authorization: token abc123XYZvaluehere"
    result = scrub(text)
    assert "abc123XYZvaluehere" not in result


def test_scrub_redacts_pem_private_key_block() -> None:
    text = (
        "before\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890abcdef\n"
        "moredataherethatlookslikebase64==\n"
        "-----END RSA PRIVATE KEY-----\n"
        "after"
    )
    result = scrub(text)
    assert "MIIEpAIBAAKCAQEA1234567890abcdef" not in result
    assert "before" in result
    assert "after" in result
    assert "***REDACTED***" in result


def test_scrub_redacts_generic_prefixed_api_key() -> None:
    text = "key is sk-abcdefghij1234567890ABCDEF"
    result = scrub(text)
    assert "sk-abcdefghij1234567890ABCDEF" not in result


def test_scrub_redacts_high_entropy_generic_token() -> None:
    text = "value=aB3dE5fG7hJ9kL1mN3oP5qR7sT9uV1wX3yZ5a1b2c3"
    result = scrub(text)
    assert "aB3dE5fG7hJ9kL1mN3oP5qR7sT9uV1wX3yZ5a1b2c3" not in result


def test_scrub_does_not_over_redact_normal_prose() -> None:
    text = (
        "This pull request fixes a bug where the parser crashed on empty "
        "input. The change adds a guard clause and a regression test. "
        "See the discussion in issue number forty two for more context."
    )
    result = scrub(text)
    assert result == text


def test_scrub_redacts_extra_secrets() -> None:
    text = "the live token is totallynotobviously-a-secret-value"
    result = scrub(text, extra_secrets=["totallynotobviously-a-secret-value"])
    assert "totallynotobviously-a-secret-value" not in result
    assert "***REDACTED***" in result


def test_scrub_does_not_redact_git_commit_sha() -> None:
    # A 40-char pure-hex token is a git commit SHA, not a secret.
    sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    text = f"fixed in commit {sha} on main"
    result = scrub(text)
    assert sha in result
    assert "***REDACTED***" not in result


def test_scrub_redacts_x_api_key_header() -> None:
    text = "x-api-key: sk-ant-abcdefghij1234567890ABCDEF\nother line"
    result = scrub(text)
    assert "sk-ant-abcdefghij1234567890ABCDEF" not in result
    assert "x-api-key: ***REDACTED***" in result
    assert "other line" in result


def test_scrub_still_redacts_x_api_key_generic_value() -> None:
    text = "x-api-key: totallynotobviously1234567890secretvalueXYZ"
    result = scrub(text)
    assert "totallynotobviously1234567890secretvalueXYZ" not in result


def test_scrub_still_redacts_real_secrets_after_sha_exclusion() -> None:
    # ghs_/Bearer/PEM/sk- must all still be redacted.
    assert "ghs_1234567890abcdefGHIJ" not in scrub("ghs_1234567890abcdefGHIJ")
    assert "sk-abcdefghij1234567890ABCDEF" not in scrub("sk-abcdefghij1234567890ABCDEF")
    bearer = scrub("Authorization: Bearer sekrit-value-here-1234")
    assert "sekrit-value-here-1234" not in bearer
    pem = scrub(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc123\n-----END RSA PRIVATE KEY-----"
    )
    assert "MIIabc123" not in pem


def test_scrub_empty_text_returns_empty() -> None:
    assert scrub("") == ""


def test_scrub_secrets_from_nested_dict_and_list() -> None:
    obj = {
        "token": "ghs_abcdefghijklmnopqrst",
        "nested": {
            "items": ["fine text", "ghp_zyxwvutsrqponmlkjih"],
        },
        "number": 42,
    }
    result = scrub_secrets_from(obj, extra_secrets=["fine-secret-value-xyz"])
    assert result["token"] == "***REDACTED***"
    assert result["nested"]["items"][0] == "fine text"
    assert result["nested"]["items"][1] == "***REDACTED***"
    assert result["number"] == 42


def test_scrub_secrets_from_extra_secret_in_nested_structure() -> None:
    obj = ["prefix", {"key": "abc-my-extra-secret-123-suffix"}]
    result = scrub_secrets_from(obj, extra_secrets=["my-extra-secret-123"])
    assert "my-extra-secret-123" not in result[1]["key"]
