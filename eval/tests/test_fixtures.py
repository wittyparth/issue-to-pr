from __future__ import annotations

import json

import pytest

from it2pr_eval.fixtures import FixtureError, load_seed_issues


def test_manifest_loads_from_package_data() -> None:
    issues = load_seed_issues()
    assert issues


def test_manifest_has_between_ten_and_fifteen_entries() -> None:
    issues = load_seed_issues()
    assert 10 <= len(issues) <= 15


def test_all_entries_reference_pinned_commit_sha() -> None:
    issues = load_seed_issues()
    for issue in issues:
        assert issue.commit_sha


def test_manifest_has_mix_of_python_and_node() -> None:
    issues = load_seed_issues()
    languages = {issue.language for issue in issues}
    assert "python" in languages
    assert "node" in languages


def test_manifest_ids_are_unique() -> None:
    issues = load_seed_issues()
    ids = [issue.id for issue in issues]
    assert len(ids) == len(set(ids))


def test_missing_commit_sha_raises() -> None:
    text = json.dumps(
        {
            "issues": [
                {
                    "id": "x",
                    "repo": "org/repo",
                    "commit_sha": "",
                    "issue_number": 1,
                    "difficulty": "easy",
                    "language": "python",
                    "expected_outcome": "fix",
                }
            ]
        }
    )
    with pytest.raises(FixtureError, match="commit_sha"):
        load_seed_issues(text)


def test_invalid_difficulty_raises() -> None:
    text = json.dumps(
        {
            "issues": [
                {
                    "id": "x",
                    "repo": "org/repo",
                    "commit_sha": "abc123",
                    "issue_number": 1,
                    "difficulty": "impossible",
                    "language": "python",
                    "expected_outcome": "fix",
                }
            ]
        }
    )
    with pytest.raises(FixtureError, match="difficulty"):
        load_seed_issues(text)


def test_missing_field_raises() -> None:
    text = json.dumps(
        {
            "issues": [
                {
                    "id": "x",
                    "repo": "org/repo",
                    "commit_sha": "abc123",
                    "issue_number": 1,
                    "difficulty": "easy",
                    "language": "python",
                }
            ]
        }
    )
    with pytest.raises(FixtureError, match="missing field"):
        load_seed_issues(text)


def test_empty_manifest_raises() -> None:
    with pytest.raises(FixtureError, match="no entries"):
        load_seed_issues(json.dumps({"issues": []}))


def test_duplicate_ids_raise() -> None:
    entry = {
        "id": "dup",
        "repo": "org/repo",
        "commit_sha": "abc123",
        "issue_number": 1,
        "difficulty": "easy",
        "language": "python",
        "expected_outcome": "fix",
    }
    text = json.dumps({"issues": [entry, entry]})
    with pytest.raises(FixtureError, match="duplicate"):
        load_seed_issues(text)
