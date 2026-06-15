# DeepResearch Agent

A pluggable LangGraph DeepResearch Agent for supplier due diligence in procurement and supply-chain workflows.

## v1 Scope

The first domain pack is `procurement`. It researches a supplier, gathers cited evidence, critiques evidence coverage, loops when evidence is insufficient, and writes a supplier due diligence report.

## Quickstart

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e ".[dev]"
pytest
deepresearch "Assess ACME Sensors for industrial sensor procurement"
```

## Architecture

```text
Planner -> Researcher -> Critic -> Researcher when evidence is missing -> Writer
```
