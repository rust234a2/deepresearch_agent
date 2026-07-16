from deepresearch_agent.eval.scope_judge import build_deepseek_scope_judge


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kw):
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


def test_judge_parses_yes():
    judge = build_deepseek_scope_judge(client=_FakeClient("是"))
    assert judge("注塑成型", "从事塑料制品注塑加工") is True


def test_judge_parses_no():
    judge = build_deepseek_scope_judge(client=_FakeClient("否"))
    assert judge("注塑成型", "餐饮服务；住宿服务") is False


def test_judge_false_on_garbage():
    judge = build_deepseek_scope_judge(client=_FakeClient(""))
    assert judge("注塑成型", "任意文本") is False


def test_judge_none_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_scope_judge() is None
