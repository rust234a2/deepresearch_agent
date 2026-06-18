# Procurement Eval v1 Design Spec

## Purpose

The procurement DeepResearch Agent already has a minimal LangGraph loop, local supplier fixtures, local retrieval, deterministic tools, a CLI, and API entrypoint. The next project milestone is not adding more retrieval infrastructure. The next milestone is proving that the agent can be evaluated.

Eval v1 provides a deterministic, CI-friendly evaluation layer for supplier due diligence. It measures whether the agent reaches the right recommendation, detects expected risks, cites evidence, handles missing information correctly, and retrieves required evidence sources.

## Problem

Without an eval layer, the project is only a demo:

- A generated report can look plausible while making the wrong supplier recommendation.
- Risk signals can be missed without any metric exposing the miss.
- Citations can exist but fail to cover the important decision dimensions.
- Public-data gaps can be hidden by overconfident writing.
- Retrieval changes cannot be compared quantitatively.

For a resume-grade Agent project, the system needs measurable behavior before adding Qdrant, MCP, databases, rerankers, or live Chinese company data sources.

## Scope

Eval v1 covers the existing procurement domain only.

It evaluates:

- final supplier recommendation
- expected risk detection
- citation coverage by research dimension
- missing-data handling
- required evidence source recall

It does not evaluate:

- LLM writing quality
- long-form analytical depth
- live web search quality
- Qdrant / OpenSearch recall
- MCP server behavior
- China public data source adapters
- cost or latency optimization

Those belong to later eval layers after the deterministic baseline is stable.

## Golden Cases

Golden cases live under:

```text
evals/procurement/golden_cases.yaml
```

Each case contains:

```yaml
case_id: northstar_restricted_supplier
question: Assess Northstar Components for control module procurement
expected:
  recommendation: reject
  expected_risks:
    - sanctions_or_blacklist
    - export_restriction
  required_dimensions:
    - supplier_profile
    - compliance
    - delivery_capability
    - negative_news
    - geopolitical_or_sanctions_risk
  required_source_ids:
    - supplier_profile:northstar-components
    - sanctions:northstar-components
    - doc:northstar-components
  allow_missing_data: false
```

The first two cases should use the existing fixtures:

- `acme_low_risk_supplier`: expected recommendation is `approve`.
- `northstar_restricted_supplier`: expected recommendation is `reject`.

A later China-specific case should model a private non-listed supplier with missing public financial data. That case should expect `conditional` or `insufficient_evidence`, not a confident approval.

## Metrics

### Recommendation Accuracy

Measures whether the final report recommendation matches the expected recommendation.

```text
recommendation_accuracy = matching_recommendations / total_cases
```

This catches the most important failure: approving a supplier that should be rejected, or rejecting a supplier that should pass.

### Risk Hit Rate

Measures whether expected risk labels appear in the report risks.

```text
risk_hit_rate = expected_risks_found / expected_risks
```

For example, if a case expects `sanctions_or_blacklist` and `export_restriction`, both must be visible in the report risk text for a full score.

### Citation Coverage

Measures whether required research dimensions are backed by cited evidence.

```text
citation_coverage = required_dimensions_with_cited_evidence / required_dimensions
```

This does not judge prose quality. It checks whether the report has evidence for the dimensions that matter.

### Missing-Data Handling Rate

Measures whether the agent handles allowed data gaps by producing open questions or an insufficient-evidence style recommendation.

This is essential for Chinese private-company due diligence, where complete audited financial data may not be publicly available.

### Retrieval Recall at K

Measures whether expected source IDs appear in the final evidence table.

```text
retrieval_recall_at_k = required_source_ids_found / required_source_ids
```

In Eval v1, `k` is represented by the evidence table produced by the current graph. Later retrieval-specific evals can measure recall at fixed retriever limits.

## Pass Criteria

A case passes when:

- recommendation matches exactly
- risk hit rate is `1.0`
- citation coverage is at least `0.75`
- missing-data handling is correct
- retrieval recall at k is at least `0.75`

The suite passes when all initial golden cases pass.

## Architecture

Add a new eval package:

```text
src/deepresearch_agent/eval/
  __init__.py
  models.py
  metrics.py
  runner.py
```

Responsibilities:

- `models.py`: typed golden-case and result models.
- `metrics.py`: pure metric functions with no LangGraph dependency.
- `runner.py`: loads cases, calls `run_research()`, computes metrics.

The runner should depend on the existing graph entrypoint:

```text
deepresearch_agent.agents.graph.run_research
```

This keeps Eval v1 focused on current system behavior without introducing a second execution path.

## CLI

Add a new command:

```powershell
.conda-env\python.exe -m deepresearch_agent.cli eval procurement
```

Expected output should include:

```text
Eval domain: procurement
Passed: 2/2
recommendation_accuracy=1.00
average_risk_hit_rate=1.00
average_citation_coverage=...
missing_data_handling_rate=...
average_retrieval_recall_at_k=...
```

The current one-question CLI behavior must remain usable for backwards compatibility.

## Testing

Eval v1 should be test-first:

- `tests/test_eval_models.py`: loads and validates golden cases.
- `tests/test_eval_metrics.py`: tests metrics with hand-built reports.
- `tests/test_eval_runner.py`: runs golden cases through the existing graph.
- `tests/test_cli.py`: verifies the `eval procurement` parser path.

The full verification command is:

```powershell
.conda-env\python.exe -m pytest -v
```

## Non-Goals

Eval v1 should not introduce:

- Qdrant
- PostgreSQL
- Redis
- OpenSearch
- live web search
- MCP servers
- LLM-as-judge
- China company data adapters

Adding those before Eval v1 would make it harder to know whether later changes improve or degrade the agent.

## Follow-Up Phases

After Eval v1 passes:

1. Add China-specific missing-data golden cases.
2. Upgrade local retrieval to BM25 and measure retrieval recall changes.
3. Add hybrid retrieval with Qdrant.
4. Add rerank metrics.
5. Move local tools behind an MCP-compatible boundary.
6. Add Postgres-backed run storage and LangGraph checkpointing.
7. Add LLM-as-judge report quality metrics after deterministic metrics are stable.

## Decision

Proceed with Eval v1 first. It is the smallest next milestone that increases engineering credibility, supports later retrieval work, and gives the project measurable behavior for resume and interview discussion.

