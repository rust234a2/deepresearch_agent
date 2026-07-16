"""起草真实扰动鲁棒性 golden（读真库 → 写 .local.yaml → 只打印各扰动类型条数）。

真企业名只写进 --output 指向的 .local.yaml（Git 忽略）；stdout 绝不打印企业名。
"""

from __future__ import annotations

import argparse

from deepresearch_agent.company_repository import CompanyRepository
from deepresearch_agent.eval.golden_gen import write_perturbation_golden


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="起草真实扰动鲁棒性 golden（仅本地、不出库）。")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", default="evals/procurement/perturbation.local.yaml")
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--per-type-n", type=int, default=25)
    args = parser.parse_args(argv)

    counts = write_perturbation_golden(
        CompanyRepository(args.database),
        args.output,
        seed=args.seed,
        per_type_n=args.per_type_n,
    )
    total = sum(counts.values())
    print(f"已写入 {args.output}（{total} 条，真名不出库）")
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
