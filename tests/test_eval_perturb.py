import random

from deepresearch_agent.eval.perturb import (
    drop_char,
    drop_suffix,
    homophone,
    noise_wrap,
    transpose,
    width_variant,
)


def test_drop_suffix_removes_trailing_designator():
    assert drop_suffix("示例科技股份有限公司") == "示例科技"
    assert drop_suffix("阿尔法精密机械有限公司") == "阿尔法精密机械"


def test_drop_suffix_none_when_no_suffix():
    assert drop_suffix("示例科技") is None


def test_transpose_swaps_one_adjacent_pair_in_stem():
    # rng 固定 → 取第 0 对相邻字对调，后缀保留
    result = transpose("示例科技股份有限公司", random.Random(0))
    assert result is not None
    assert result != "示例科技股份有限公司"
    assert result.endswith("股份有限公司")
    # 词干长度不变、仍是 4 字 + 原后缀
    assert len(result) == len("示例科技股份有限公司")


def test_transpose_none_when_stem_too_short():
    assert transpose("A公司", random.Random(0)) is None  # 词干 "A" 1 字


def test_width_variant_converts_ascii_to_fullwidth():
    # ASCII 字母数字转全角；纯中文名无 ASCII → None
    assert width_variant("ABC智能装备有限公司") == "ＡＢＣ智能装备有限公司"
    assert width_variant("示例科技股份有限公司") is None


def test_noise_wrap_wraps_into_sentence():
    assert noise_wrap("示例科技股份有限公司") == "核验示例科技股份有限公司的工商信息"


def test_homophone_substitutes_first_mapped_char():
    # 词干 "示例科技" 里 "科"→"颗"（同音），后缀保留
    assert homophone("示例科技股份有限公司") == "示例颗技股份有限公司"


def test_homophone_none_when_no_mapped_char():
    assert homophone("甲乙丙有限公司") is None


def test_drop_char_removes_one_stem_char():
    result = drop_char("示例科技股份有限公司", random.Random(0))
    assert result is not None
    assert result.endswith("股份有限公司")
    assert len(result) == len("示例科技股份有限公司") - 1


def test_drop_char_none_when_stem_too_short():
    assert drop_char("AB公司", random.Random(0)) is None  # 词干 "AB" 2 字 < 3
