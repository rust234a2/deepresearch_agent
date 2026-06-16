# DeepResearch Agent

An open-source, pluggable DeepResearch Agent framework built on LangGraph. The v1 domain is supplier due diligence for procurement and supply-chain decisions.

## When To Use This

Use DeepResearch when an answer requires gathering evidence from many sources, deciding what to search next, resolving missing evidence, and producing a cited report. Do not use it for single-fact lookup, one-authority-source questions, or latency-sensitive chat.

## v1 Demo

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e ".[dev]"
pytest
deepresearch "Assess ACME Sensors for industrial sensor procurement"
```

For the local conda environment used during development in this workspace:

```powershell
conda activate E:\vibe_coding_prj\deepresearch_agent\.conda-env
python -m deepresearch_agent.cli "Assess ACME Sensors for industrial sensor procurement"
```

## API

```bash
uvicorn deepresearch_agent.api:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Assess ACME Sensors for industrial sensor procurement\"}"
```

## Architecture

```text
Planner -> Researcher -> Critic -> Researcher when evidence is missing -> Writer
```

The procurement domain pack defines research dimensions, allowed tools, report sections, source priority, and HITL policy. The core graph is domain-independent enough to support later investment or academic research packs.

## Roadmap

- Add BM25 + vector hybrid retrieval with alpha tuning.
- Add Qdrant and reranker support.
- Extract procurement tools into an MCP server.
- Add LangSmith trace and local trace export.
- Add golden supplier cases and trajectory evaluation.
