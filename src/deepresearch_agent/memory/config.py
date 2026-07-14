from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_CHROMA_PATH = "data/procurement/derived/mem0_chroma"
DEFAULT_EMBEDDER_MODEL = "BAAI/bge-small-zh-v1.5"


@dataclass
class MemoryConfig:
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    embedder_model: str = DEFAULT_EMBEDDER_MODEL
    vector_store_path: str = DEFAULT_CHROMA_PATH
    collection_name: str = "procurement_memory"

    @classmethod
    def deepseek(cls, **kwargs) -> MemoryConfig:
        return cls(**kwargs)

    @classmethod
    def ollama(
        cls,
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        **kwargs,
    ) -> MemoryConfig:
        return cls(
            llm_provider="ollama",
            llm_model=model,
            llm_base_url=base_url,
            api_key_env="",
            **kwargs,
        )

    def to_mem0_config(self) -> dict:
        if self.llm_provider == "ollama":
            llm = {
                "provider": "ollama",
                "config": {"model": self.llm_model, "ollama_base_url": self.llm_base_url},
            }
        else:
            llm = {
                "provider": "openai",
                "config": {
                    "model": self.llm_model,
                    "openai_base_url": self.llm_base_url,
                    "api_key": os.environ.get(self.api_key_env, ""),
                },
            }
        return {
            "llm": llm,
            "embedder": {"provider": "huggingface", "config": {"model": self.embedder_model}},
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": self.collection_name,
                    "path": self.vector_store_path,
                },
            },
        }


def build_memory_backend(config: MemoryConfig | None = None):
    config = config or MemoryConfig()
    if config.llm_provider == "deepseek" and not os.environ.get(config.api_key_env):
        return None
    try:
        from mem0 import Memory

        from deepresearch_agent.memory.service import Mem0Backend

        memory = Memory.from_config(config.to_mem0_config())
        return Mem0Backend(memory)
    except Exception:
        return None
