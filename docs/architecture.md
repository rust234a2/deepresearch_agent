# Architecture

## Core Loop

The v1 graph uses LangGraph because supplier due diligence is not a linear chain. The agent must plan dimensions, gather evidence, critique coverage, and loop back to retrieval when evidence is missing.

## Nodes

- `planner`: extracts supplier and creates dimension-specific research questions.
- `researcher`: calls deterministic procurement tools and local retrieval.
- `critic`: checks evidence coverage against the plan.
- `writer`: creates a cited supplier due diligence report.

## Domain Pack Boundary

The procurement domain pack lives in `domains/procurement/domain.yaml`. Later domains should define their own dimensions, allowed tools, report sections, source priority, and HITL rules without rewriting the graph.

## Tool Boundary

The v1 tool registry records name, description, permission tier, timeout, latency, and structured results. This is intentionally close to MCP tool metadata so the tools can be moved behind an MCP server in a later milestone.
