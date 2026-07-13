from deepresearch_agent.llm.deepseek import build_deepseek_polisher, _render_report_for_llm


class _FakeChunk:
    def __init__(self, text): self.choices = [type("C", (), {"delta": type("D", (), {"content": text})()})()]


class _FakeStream:
    def __iter__(self): return iter([_FakeChunk("甲公司"), _FakeChunk("经营范围…"), _FakeChunk("")])


class _FakeCompletions:
    def create(self, **kw): return _FakeStream()


class _FakeClient:
    chat = type("Chat", (), {"completions": _FakeCompletions()})()


def _graph_report():
    return {
        "recommendation": "insufficient_evidence", "query": "找股东有关联的供应商",
        "summary": "检索到 2 家候选。",
        "candidates": [{"legal_name": "丙公司", "top_score": 0.8, "ultimate_controllers": ["张三"]}],
        "shared_controllers": [{"controller_name": "张三", "controlled_companies": ["丙公司", "丁公司"], "note": "经企业股权链推断"}],
    }


def test_render_includes_facts_excludes_conclusion():
    text = _render_report_for_llm("graph", _graph_report())
    assert "丙公司" in text and "张三" in text
    assert "证据不足" not in text  # 结论句不进 LLM 输入


def test_polisher_streams_tokens_from_client():
    polisher = build_deepseek_polisher(client=_FakeClient())
    tokens = list(polisher("graph", _graph_report()))
    assert "甲公司" in tokens
    assert "" not in tokens  # 空 delta 被过滤


def test_polisher_none_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_polisher() is None
