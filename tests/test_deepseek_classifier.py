from deepresearch_agent.llm.deepseek import _parse_level, build_deepseek_classifier


def test_no_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_deepseek_classifier() is None


def test_parse_level_extracts_or_none():
    assert _parse_level("complex") == "complex"
    assert _parse_level(" Simple ") == "simple"
    assert _parse_level("这个查询是 medium 级") == "medium"
    assert _parse_level("垃圾输出") is None
    assert _parse_level(None) is None


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content):
        self.chat = _FakeChat(content)


def test_classify_with_injected_client_parses_level():
    classify = build_deepseek_classifier(client=_FakeClient("complex"))
    assert classify is not None
    assert classify("示例查询") == "complex"


def test_classify_with_bad_response_returns_none():
    classify = build_deepseek_classifier(client=_FakeClient("我不确定"))
    assert classify("x") is None
