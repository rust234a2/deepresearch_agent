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


# 常见公司名用字的同音替换表（手工整理、确定性代理、零依赖；覆盖有限——
# 词干里没命中的企业该扰动返回 None）。比"相邻字对调"更贴近中文拼音输入法的真实错法。
_HOMOPHONES: dict[str, str] = {
    "科": "颗", "技": "际", "精": "晶", "密": "蜜", "械": "卸",
    "机": "基", "电": "店", "子": "紫", "设": "社", "智": "志",
    "装": "庄", "备": "倍", "材": "财", "仪": "宜", "器": "气",
    "传": "船", "感": "敢", "造": "灶", "制": "治", "业": "叶",
    "工": "公", "自": "字", "动": "洞", "实": "食", "泽": "责",
    "华": "滑", "达": "答", "新": "芯", "源": "元", "力": "立",
}


def homophone(name: str) -> str | None:
    """把词干里第一个可映射字替换成同音异字（错字的真实代理）；无可映射字 → None。"""
    stem = _stem(name)
    for i, ch in enumerate(stem):
        if ch in _HOMOPHONES:
            return stem[:i] + _HOMOPHONES[ch] + stem[i + 1 :] + name[len(stem) :]
    return None


def drop_char(name: str, rng: random.Random) -> str | None:
    """从词干随机删一个字（漏字）；词干 < 3 字（删后 < 2）→ None。"""
    stem = _stem(name)
    if len(stem) < 3:
        return None
    i = rng.randrange(len(stem))
    return stem[:i] + stem[i + 1 :] + name[len(stem) :]
