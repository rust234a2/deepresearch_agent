from __future__ import annotations

import random
from pathlib import Path

import yaml

from deepresearch_agent.company_database import normalize_company_name
from deepresearch_agent.company_repository import _contains_name
from deepresearch_agent.eval.models import GoldenEntityCase
from deepresearch_agent.eval.perturb import (
    _stem,
    drop_suffix,
    noise_wrap,
    transpose,
    width_variant,
)


def _build_name_index(
    company_names: dict[str, str], aliases: list[tuple[str, str]]
) -> dict[str, set[str]]:
    """归一化名 → 代码集，over 法定名 ∪ 曾用名。真值的唯一来源。"""
    index: dict[str, set[str]] = {}
    for code, legal in company_names.items():
        index.setdefault(normalize_company_name(legal), set()).add(code)
    for code, alias in aliases:
        index.setdefault(normalize_company_name(alias), set()).add(code)
    return index


def generate_entity_golden(
    company_names: dict[str, str],
    aliases: list[tuple[str, str]],
    *,
    seed: int = 20260712,
    n_legal: int = 25,
    n_alias: int = 15,
    n_not_found: int = 10,
    ambiguous_cap: int = 25,
) -> list[GoldenEntityCase]:
    rng = random.Random(seed)
    name_to_codes = _build_name_index(company_names, aliases)
    cases: list[GoldenEntityCase] = []

    # 1) resolved 法定名：归一化法定名唯一映射到本代码（排除同名/被 alias 撞名的）
    legal_pool = sorted(
        code
        for code, legal in company_names.items()
        if name_to_codes[normalize_company_name(legal)] == {code}
    )
    rng.shuffle(legal_pool)
    for i, code in enumerate(legal_pool[:n_legal]):
        cases.append(
            GoldenEntityCase(
                case_id=f"resolved_legal_{i}",
                question=company_names[code],
                expected_status="resolved",
                expected_code=code,
            )
        )

    # 2) resolved 曾用名：该 alias 归一化后唯一映射到本代码
    alias_pool = sorted(
        (code, alias)
        for code, alias in aliases
        if name_to_codes[normalize_company_name(alias)] == {code}
    )
    rng.shuffle(alias_pool)
    for i, (code, alias) in enumerate(alias_pool[:n_alias]):
        cases.append(
            GoldenEntityCase(
                case_id=f"resolved_alias_{i}",
                question=alias,
                expected_status="resolved",
                expected_code=code,
            )
        )

    # 3) ambiguous：归一化名映射到 ≥2 代码；查询用一个原始拼写
    original_by_norm: dict[str, str] = {}
    for code, legal in company_names.items():
        original_by_norm.setdefault(normalize_company_name(legal), legal)
    for code, alias in aliases:
        original_by_norm.setdefault(normalize_company_name(alias), alias)
    ambiguous_norms = sorted(norm for norm, codes in name_to_codes.items() if len(codes) >= 2)
    dropped = max(0, len(ambiguous_norms) - ambiguous_cap)
    for i, norm in enumerate(ambiguous_norms[:ambiguous_cap]):
        cases.append(
            GoldenEntityCase(
                case_id=f"ambiguous_{i}",
                question=original_by_norm[norm],
                expected_status="ambiguous",
                expected_candidate_codes=sorted(name_to_codes[norm]),
            )
        )
    if dropped:
        print(f"[golden_gen] ambiguous 候选超 cap，丢弃 {dropped} 条")

    # 4) not_found：合成名，校验库中无任何名被其包含
    made = 0
    attempt = 0
    while made < n_not_found:
        question = f"核验{seed}号不存在测试企业{attempt}有限公司"
        attempt += 1
        nq = normalize_company_name(question)
        if any(_contains_name(nq, name) for name in name_to_codes):
            continue
        cases.append(
            GoldenEntityCase(
                case_id=f"not_found_{made}",
                question=question,
                expected_status="not_found",
            )
        )
        made += 1

    return cases


def category_counts(cases: list[GoldenEntityCase]) -> dict[str, int]:
    counts = {"resolved_legal": 0, "resolved_alias": 0, "ambiguous": 0, "not_found": 0}
    for case in cases:
        for prefix in counts:
            if case.case_id.startswith(prefix):
                counts[prefix] += 1
                break
    return counts


def _case_to_dict(case: GoldenEntityCase) -> dict:
    data = {
        "case_id": case.case_id,
        "question": case.question,
        "expected_status": case.expected_status,
    }
    if case.expected_code is not None:
        data["expected_code"] = case.expected_code
    if case.expected_candidate_codes:
        data["expected_candidate_codes"] = case.expected_candidate_codes
    if case.perturbation_type is not None:
        data["perturbation_type"] = case.perturbation_type
    return data


def write_golden(
    repository,
    output_path,
    *,
    seed: int = 20260712,
    n_legal: int = 25,
    n_alias: int = 15,
    n_not_found: int = 10,
    ambiguous_cap: int = 25,
) -> dict[str, int]:
    cases = generate_entity_golden(
        repository.get_all_company_names(),
        repository.iter_aliases(),
        seed=seed,
        n_legal=n_legal,
        n_alias=n_alias,
        n_not_found=n_not_found,
        ambiguous_cap=ambiguous_cap,
    )
    payload = {"cases": [_case_to_dict(c) for c in cases]}
    Path(output_path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return category_counts(cases)


_PERTURBERS: tuple[str, ...] = ("drop_suffix", "transpose", "width_variant", "noise_wrap")


def _apply_perturber(ptype: str, name: str, rng: random.Random) -> str | None:
    if ptype == "drop_suffix":
        return drop_suffix(name)
    if ptype == "transpose":
        return transpose(name, rng)
    if ptype == "width_variant":
        return width_variant(name)
    if ptype == "noise_wrap":
        return noise_wrap(name)
    return None


def _unique_stem_seeds(
    company_names: dict[str, str], aliases: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """选词干（去后缀、≥4 字）在全库唯一的企业作种子。独立粗粒度子串扫描，非 resolver 逻辑。"""
    corpus = [(code, normalize_company_name(legal)) for code, legal in company_names.items()]
    corpus += [(code, normalize_company_name(alias)) for code, alias in aliases]
    seeds: list[tuple[str, str]] = []
    for code, legal in company_names.items():
        stem = normalize_company_name(_stem(legal))
        if len(stem) < 4:
            continue
        if any(other_code != code and stem in other_norm for other_code, other_norm in corpus):
            continue
        seeds.append((code, legal))
    return sorted(seeds)


def generate_perturbation_golden(
    company_names: dict[str, str],
    aliases: list[tuple[str, str]],
    *,
    seed: int = 20260716,
    per_type_n: int = 25,
) -> list[GoldenEntityCase]:
    rng = random.Random(seed)
    seeds = _unique_stem_seeds(company_names, aliases)
    all_norm_names = [(code, normalize_company_name(n)) for code, n in company_names.items()]
    cases: list[GoldenEntityCase] = []
    for ptype in _PERTURBERS:
        order = list(seeds)
        rng.shuffle(order)
        made = 0
        for code, legal in order:
            if made >= per_type_n:
                break
            perturbed = _apply_perturber(ptype, legal, rng)
            if perturbed is None:
                continue
            nperturbed = normalize_company_name(perturbed)
            # 来源纯净：跳过意外重引别家完整名的扰动
            if any(oc != code and on and on in nperturbed for oc, on in all_norm_names):
                continue
            cases.append(
                GoldenEntityCase(
                    case_id=f"{ptype}_{made}",
                    question=perturbed,
                    expected_status="resolved",
                    expected_code=code,
                    perturbation_type=ptype,
                )
            )
            made += 1
    return cases


def perturbation_category_counts(cases: list[GoldenEntityCase]) -> dict[str, int]:
    counts = {ptype: 0 for ptype in _PERTURBERS}
    for case in cases:
        if case.perturbation_type in counts:
            counts[case.perturbation_type] += 1
    return counts


def write_perturbation_golden(
    repository,
    output_path,
    *,
    seed: int = 20260716,
    per_type_n: int = 25,
) -> dict[str, int]:
    cases = generate_perturbation_golden(
        repository.get_all_company_names(),
        repository.iter_aliases(),
        seed=seed,
        per_type_n=per_type_n,
    )
    payload = {"cases": [_case_to_dict(c) for c in cases]}
    Path(output_path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return perturbation_category_counts(cases)
