"""除外ルールの検証と判定。"""

from __future__ import annotations

import pytest

from hph.rules import MAX_RULES, ExcludeRule, is_excluded, parse_rules


def _rule(target: str, match: str, value: str) -> dict[str, str]:
    return {"target": target, "match": match, "value": value}


@pytest.mark.parametrize(
    ("match", "value", "name", "expected"),
    [
        ("equals", "build", "build", True),
        ("equals", "build", "builder", False),
        ("contains", "draft", "my-Draft-v2", True),
        ("prefix", "tmp", "TMP_notes", True),
        ("prefix", "tmp", "notes_tmp", False),
        ("suffix", ".bak.html", "a.BAK.html", True),
        ("suffix", "old", "old-notes", False),
    ],
)
def test_matches_ignore_case(match: str, value: str, name: str, expected: bool) -> None:
    rules = parse_rules([_rule("folder", match, value)])
    assert is_excluded(name, "folder", rules) is expected


def test_target_is_respected() -> None:
    rules = parse_rules([_rule("folder", "equals", "draft")])
    assert is_excluded("draft", "file", rules) is False


def test_value_is_trimmed_and_duplicates_collapse() -> None:
    rules = parse_rules([_rule("file", "contains", " Draft "), _rule("file", "contains", "draft")])
    assert rules == (ExcludeRule("file", "contains", "Draft"),)


def test_to_dict_roundtrip() -> None:
    rule = ExcludeRule("folder", "prefix", "tmp")
    assert parse_rules([rule.to_dict()]) == (rule,)


@pytest.mark.parametrize(
    "raw",
    [
        "draft",
        [_rule("path", "equals", "x")],
        [_rule("folder", "regex", "x")],
        [_rule("folder", "equals", "   ")],
        [_rule("folder", "equals", "a/b")],
        [_rule("folder", "equals", "a\\b")],
        [_rule("folder", "equals", "x" * 201)],
        [{"target": "folder", "match": "equals", "value": 3}],
        ["not-a-dict"],
    ],
)
def test_invalid_rules_raise(raw: object) -> None:
    with pytest.raises(ValueError):
        parse_rules(raw)


def test_too_many_rules_raise() -> None:
    with pytest.raises(ValueError):
        parse_rules([_rule("file", "equals", f"n{i}") for i in range(MAX_RULES + 1)])
