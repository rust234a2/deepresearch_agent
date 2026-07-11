"""起草真实企业识别 golden（读真库 → 写 .local.yaml → 只打印各类条数）。

真企业名只写进 --output 指向的 .local.yaml（Git 忽略）；stdout 绝不打印企业名。
"""

from __future__ import annotations

import argparse

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.golden_gen import write_golden


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="起草真实企业识别 golden（仅本地、不出库）。")
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--output", default="evals/procurement/entity_resolution.local.yaml"
    )
    parser.add_argument("--seed", type=int, default=20260712)
    parser.add_argument("--n-legal", type=int, default=25)
    parser.add_argument("--n-alias", type=int, default=15)
    parser.add_argument("--n-not-found", type=int, default=10)
    parser.add_argument("--ambiguous-cap", type=int, default=25)
    args = parser.parse_args(argv)

    counts = write_golden(
        CompanyRepository(args.database),
        args.output,
        seed=args.seed,
        n_legal=args.n_legal,
        n_alias=args.n_alias,
        n_not_found=args.n_not_found,
        ambiguous_cap=args.ambiguous_cap,
    )
    total = sum(counts.values())
    print(f"已写入 {args.output}（{total} 条，真名不出库）")
    print(
        f"  法定名={counts['resolved_legal']}  曾用名={counts['resolved_alias']}  "
        f"歧义={counts['ambiguous']}  not_found={counts['not_found']}"
    )


if __name__ == "__main__":
    main()
