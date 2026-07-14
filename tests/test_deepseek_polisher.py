from deepresearch_agent.llm.deepseek import _render_report_for_llm, build_deepseek_polisher


class _FakeChunk:
    def __init__(self, text): self.choices = [type("C", (), {"delta": type("D", (), {"content": text})()})()]


class _FakeStream:
    def __iter__(self): return iter([_FakeChunk("甲公司"), _FakeChunk("经营范围…"), _FakeChunk("")])


class _LiteralNlStream:
    def __iter__(self): return iter([_FakeChunk("甲公司\\n\\n经营范围")])  # LLM 吐字面反斜杠n


class _LiteralNlCompletions:
    def create(self, **kw): return _LiteralNlStream()


class _LiteralNlClient:
    chat = type("Chat", (), {"completions": _LiteralNlCompletions()})()


class _SplitNlStream:
    # 字面 \n 被拆在两个 token 里：反斜杠在前一 token 末尾，n 在后一 token 开头
    def __iter__(self): return iter([_FakeChunk("甲公司\\"), _FakeChunk("n乙公司")])


class _SplitNlCompletions:
    def create(self, **kw): return _SplitNlStream()


class _SplitNlClient:
    chat = type("Chat", (), {"completions": _SplitNlCompletions()})()


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


def test_render_includes_graph_facts_without_recommendation_conclusion():
    text = _render_report_for_llm("graph", _graph_report())
    assert "丙公司" in text and "张三" in text
    assert "证据不足" not in text


def test_render_named_drops_summary_and_risks():
    # summary 与 risks 都可能含结论式表述，不得进入 LLM 输入。
    report = {
        "recommendation": "insufficient_evidence",
        "supplier_name": "亚联机械股份有限公司",
        "summary": "已完成核验；现有数据不足以作出采购批准或风险结论。",
        "evidence_table": [{"dimension": "registration", "claim": "登记状态：存续"}],
        "risks": ["当前数据源不包含制裁、司法数据，不能据此作出采购批准或风险结论。"],
        "open_questions": ["接入制裁和监管名单数据。"],
    }
    text = _render_report_for_llm("named", report)  # 不传 conclusion
    assert "登记状态：存续" in text                  # 事实仍在
    assert "接入制裁和监管名单数据" in text          # 待接入数据仍在
    assert "采购批准或风险结论" not in text          # summary/risks 的结论式表述不进输入


def test_polisher_cleans_literal_newline_split_across_tokens():
    polisher = build_deepseek_polisher(client=_SplitNlClient())
    text = "".join(polisher("named", {"supplier_name": "甲公司"}))
    assert "\\n" not in text       # 跨 token 的字面反斜杠n 也被清理
    assert "\n" in text            # 变真换行
    assert "甲公司" in text and "乙公司" in text


def test_polisher_streams_tokens_from_client():
    polisher = build_deepseek_polisher(client=_FakeClient())
    tokens = list(polisher("graph", _graph_report()))
    assert "甲公司" in tokens
    assert "" not in tokens  # 空 delta 被过滤


def test_polisher_none_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_polisher() is None


def test_polisher_converts_literal_newline_to_real():
    polisher = build_deepseek_polisher(client=_LiteralNlClient())
    text = "".join(polisher("named", {"supplier_name": "甲公司"}))
    assert "\\n" not in text       # 字面反斜杠n 已清理
    assert "\n" in text            # 变成真换行
