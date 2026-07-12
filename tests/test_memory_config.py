from deepresearch_agent.memory.config import MemoryConfig, build_memory_backend


def test_deepseek_config_shape():
    cfg = MemoryConfig.deepseek()
    m = cfg.to_mem0_config()
    assert m["llm"]["provider"] == "openai"  # DeepSeek 走 openai 兼容
    assert m["llm"]["config"]["model"] == "deepseek-chat"
    assert "deepseek.com" in m["llm"]["config"]["openai_base_url"]
    assert m["embedder"]["provider"] == "huggingface"
    assert m["embedder"]["config"]["model"] == "BAAI/bge-small-zh-v1.5"
    assert m["vector_store"]["provider"] == "chroma"
    assert m["vector_store"]["config"]["collection_name"] == "procurement_memory"


def test_ollama_config_preserves_local_interface():
    cfg = MemoryConfig.ollama()
    m = cfg.to_mem0_config()
    assert m["llm"]["provider"] == "ollama"
    assert m["llm"]["config"]["model"] == "qwen2.5:3b"
    assert "localhost" in m["llm"]["config"]["ollama_base_url"]
    # 嵌入器/向量库仍本地
    assert m["embedder"]["provider"] == "huggingface"
    assert m["vector_store"]["provider"] == "chroma"


def test_build_backend_none_when_no_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert build_memory_backend(MemoryConfig.deepseek()) is None


def test_build_backend_none_when_mem0_absent(monkeypatch):
    # 有 key 但 mem0 未安装（CI 环境）→ import 失败被吞 → None
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy")
    assert build_memory_backend(MemoryConfig.deepseek()) is None
