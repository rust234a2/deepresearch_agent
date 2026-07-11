import pytest

pytest.importorskip("opentelemetry")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from deepresearch_agent.observability import (
    configure_tracing,
    get_tracer,
    reset_tracing,
    traced_node,
)


@pytest.fixture(autouse=True)
def _clean_tracing():
    reset_tracing()
    yield
    reset_tracing()


def test_get_tracer_none_before_configure():
    assert get_tracer() is None


def test_traced_node_passthrough_when_unconfigured():
    calls = []

    def node(state):
        calls.append(state)
        return {"ok": state}

    wrapped = traced_node("planner", node)
    result = wrapped("S")
    assert result == {"ok": "S"} and calls == ["S"]


def test_traced_node_emits_span_with_attrs():
    mem = InMemorySpanExporter()
    configure_tracing(exporter=mem)

    def node(state):
        return {"retrieval_mode": "graph"}

    wrapped = traced_node(
        "researcher", node, attr_fn=lambda s: {"retrieval_mode": s["retrieval_mode"]}
    )
    out = wrapped("S")

    assert out == {"retrieval_mode": "graph"}
    spans = mem.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "researcher"
    assert spans[0].attributes["retrieval_mode"] == "graph"


def test_configure_tracing_idempotent():
    mem1 = InMemorySpanExporter()
    p1 = configure_tracing(exporter=mem1)
    p2 = configure_tracing(exporter=InMemorySpanExporter())
    assert p1 is p2  # 第二次不覆盖
