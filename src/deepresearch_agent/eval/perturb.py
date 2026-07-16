from __future__ import annotations

import random

from deepresearch_agent.company_repository import _COMPANY_SUFFIXES


def _stem(name: str) -> str:
    """去掉尾部一个公司后缀取词干（后缀表复用 resolver 常量；独立性在匹配逻辑不在此表）。"""
    for suffix in _COMPANY_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def drop_suffix(name: str) -> str | None:
    """去掉尾部一个公司后缀；无已知后缀或去后为空 → None。"""
    for suffix in _COMPANY_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return None


def transpose(name: str, rng: random.Random) -> str | None:
    """词干内随机取一对相邻字符对调（错字的确定性代理）；词干 < 2 字 → None。"""
    stem = _stem(name)
    if len(stem) < 2:
        return None
    i = rng.randrange(len(stem) - 1)
    swapped = stem[:i] + stem[i + 1] + stem[i] + stem[i + 2 :]
    return swapped + name[len(stem) :]


def width_variant(name: str) -> str | None:
    """把 ASCII 字母数字转全角（NFKC 应折回）；无 ASCII 字母数字 → None。"""
    out: list[str] = []
    changed = False
    for ch in name:
        if ("0" <= ch <= "9") or ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            out.append(chr(ord(ch) + 0xFEE0))
            changed = True
        else:
            out.append(ch)
    return "".join(out) if changed else None


def noise_wrap(name: str) -> str | None:
    """包成整句（测试全名子串段是否被句子干扰）；恒可用。"""
    return f"核验{name}的工商信息"
