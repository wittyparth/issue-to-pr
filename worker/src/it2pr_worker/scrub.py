"""Secret scrubber (M5, CRITICAL-4 / M7 security follow-up).

Redacts GitHub tokens, Authorization headers, PEM private-key blocks, and
generic high-entropy API-key-looking strings from any text that is about to
be logged, archived, or written into a PR body. Also redacts any
explicitly-passed `extra_secrets` (e.g. the run's live installation token) so
callers don't need a pattern for values they already know are secret.

Conservative by design: the generic-token pattern requires a long run of
mixed-case/digit characters so ordinary prose is not over-redacted.
"""

from __future__ import annotations

import re
from typing import Any

_REDACTED = "***REDACTED***"

# GitHub token prefixes: ghs_ (installation), ghp_ (personal), github_pat_ (fine-grained).
_GITHUB_TOKEN_RE = re.compile(r"\b(?:ghs_|ghp_|github_pat_)[A-Za-z0-9_]{10,}\b")

# Authorization: Bearer <token> / token <token> / Basic <base64> headers
# (case-insensitive scheme). Basic covers git's smart-HTTP auth (see
# git_ops.py), which git-clone/push failures can otherwise leak verbatim via
# a CalledProcessError's argv.
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(Authorization\s*:\s*(?:Bearer|token|Basic)\s+)([^\s\"'\\]+)"
)

# x-api-key: <value> headers (Anthropic authenticates with x-api-key, not Authorization).
_X_API_KEY_HEADER_RE = re.compile(
    r"(?i)\b(x-api-key\s*:\s*)([^\s\"'\\]+)"
)

# Pure-hex 7..40 char tokens are git commit SHAs, not secrets; exclude from redaction.
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# PEM blocks of any kind (private keys, certs treated conservatively as private keys only).
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Generic API-key-looking tokens, e.g. sk-..., xoxb-..., or bare 40+ char
# high-entropy runs mixing letters and digits. Conservative: requires both a
# letter and a digit in the run to avoid matching plain English words.
_GENERIC_KEY_PREFIXED_RE = re.compile(r"\b(?:sk|pk|xox[baprs])-[A-Za-z0-9_-]{10,}\b")
_HIGH_ENTROPY_RE = re.compile(
    r"\b(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{40,}\b"
)


def _redact_auth_header(match: re.Match[str]) -> str:
    return f"{match.group(1)}{_REDACTED}"


def _redact_high_entropy(match: re.Match[str]) -> str:
    token = match.group(0)
    # A 40-char (or shorter) pure-hex token is a git commit SHA, not a secret.
    if _GIT_SHA_RE.fullmatch(token):
        return token
    return _REDACTED


def scrub(text: str, *, extra_secrets: list[str] | None = None) -> str:
    """Return `text` with all recognized secret patterns replaced by a marker."""
    if not text:
        return text

    result = text
    result = _PEM_BLOCK_RE.sub(_REDACTED, result)
    result = _AUTH_HEADER_RE.sub(_redact_auth_header, result)
    result = _X_API_KEY_HEADER_RE.sub(_redact_auth_header, result)
    result = _GITHUB_TOKEN_RE.sub(_REDACTED, result)
    result = _GENERIC_KEY_PREFIXED_RE.sub(_REDACTED, result)
    result = _HIGH_ENTROPY_RE.sub(_redact_high_entropy, result)

    for secret in extra_secrets or []:
        if secret:
            result = result.replace(secret, _REDACTED)

    return result


def scrub_secrets_from(obj: Any, extra_secrets: list[str] | None = None) -> Any:  # noqa: ANN401
    """Recursively scrub strings inside nested dict/list/str structures (for M7)."""
    if isinstance(obj, str):
        return scrub(obj, extra_secrets=extra_secrets)
    if isinstance(obj, dict):
        return {key: scrub_secrets_from(value, extra_secrets) for key, value in obj.items()}
    if isinstance(obj, list):
        return [scrub_secrets_from(item, extra_secrets) for item in obj]
    if isinstance(obj, tuple):
        return tuple(scrub_secrets_from(item, extra_secrets) for item in obj)
    return obj
