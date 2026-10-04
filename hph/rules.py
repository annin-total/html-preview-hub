"""除外ルール（フォルダ名・ファイル名の条件）の検証と判定。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

TARGETS = ("folder", "file")
MATCHES = ("equals", "contains", "prefix", "suffix")
MAX_RULES = 100
MAX_VALUE_LENGTH = 200

_MATCHERS: dict[str, Callable[[str, str], bool]] = {
    "equals": lambda name, value: name == value,
    "contains": lambda name, value: value in name,
    "prefix": lambda name, value: name.startswith(value),
    "suffix": lambda name, value: name.endswith(value),
}


@dataclass(frozen=True)
class ExcludeRule:
    """「対象（フォルダ名・ファイル名）が値に条件で当てはまれば除外する」ルール。"""

    target: str
    match: str
    value: str

    def to_dict(self) -> dict[str, str]:
        """設定ファイルと API に書き出す形へ変換する。"""
        return {"target": self.target, "match": self.match, "value": self.value}


def parse_rules(raw: object) -> tuple[ExcludeRule, ...]:
    """設定ファイル・API の値を検証してルールの列にする。不正なら ValueError。"""
    if not isinstance(raw, list):
        raise ValueError("除外の指定が不正です（リストが必要です）")
    rules: list[ExcludeRule] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw:
        rule = _parse_rule(item)
        key = (rule.target, rule.match, rule.value.casefold())
        if key not in seen:
            seen.add(key)
            rules.append(rule)
    if len(rules) > MAX_RULES:
        raise ValueError(f"除外は {MAX_RULES} 件までです")
    return tuple(rules)


def is_excluded(name: str, target: str, rules: Iterable[ExcludeRule]) -> bool:
    """名前が、対象の一致するルールのどれかに当てはまるか（大文字・小文字は区別しない）。"""
    folded = name.casefold()
    return any(
        rule.target == target and _MATCHERS[rule.match](folded, rule.value.casefold()) for rule in rules
    )


def _parse_rule(item: object) -> ExcludeRule:
    if not isinstance(item, dict):
        raise ValueError("除外の指定が不正です")
    target, match, value = item.get("target"), item.get("match"), item.get("value")
    if target not in TARGETS or match not in MATCHES or not isinstance(value, str):
        raise ValueError("除外の指定が不正です（対象・条件・値を確かめてください）")
    value = value.strip()
    if not value:
        raise ValueError("除外する名前を入力してください")
    if len(value) > MAX_VALUE_LENGTH:
        raise ValueError(f"除外する名前は {MAX_VALUE_LENGTH} 文字までです")
    if "/" in value or "\\" in value:
        raise ValueError("除外する名前に / や \\ は使えません")
    return ExcludeRule(target, match, value)
