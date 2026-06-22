from deepresearch_agent.rag.chunking import ScopeChunk, chunk_business_scope


def test_chunk_splits_items_without_section_label():
    chunks = chunk_business_scope("工业设备制造；工业设备销售。")
    assert chunks == [
        ScopeChunk(section_label=None, ordinal=0, text="工业设备制造"),
        ScopeChunk(section_label=None, ordinal=1, text="工业设备销售"),
    ]


def test_chunk_handles_sections_labels_and_disclaimer():
    text = (
        "许可项目：建设工程施工；检验检测服务"
        "（依法须经批准的项目，经相关部门批准后方可开展经营活动）"
        "***一般项目：工业设备制造、机械零件加工"
    )
    chunks = chunk_business_scope(text)
    assert chunks == [
        ScopeChunk(section_label="许可项目", ordinal=0, text="建设工程施工"),
        ScopeChunk(section_label="许可项目", ordinal=1, text="检验检测服务"),
        ScopeChunk(section_label="一般项目", ordinal=2, text="工业设备制造"),
        ScopeChunk(section_label="一般项目", ordinal=3, text="机械零件加工"),
    ]


def test_chunk_dedupes_within_section_and_drops_blanks():
    chunks = chunk_business_scope("工业设备制造；工业设备制造；；")
    assert [c.text for c in chunks] == ["工业设备制造"]


def test_chunk_returns_empty_for_missing_scope():
    assert chunk_business_scope(None) == []
    assert chunk_business_scope("   ") == []
