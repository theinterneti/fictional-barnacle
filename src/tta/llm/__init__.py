"""LLM integration layer."""

__all__ = ["LiteLLMClient"]

def __getattr__(name: str):
    if name == "LiteLLMClient":
        from tta.llm.litellm_client import LiteLLMClient

        return LiteLLMClient
    raise AttributeError(f"module 'tta.llm' has no attribute {name!r}")
