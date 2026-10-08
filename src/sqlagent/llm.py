from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from .config import Settings


def build_llm(settings: Settings) -> BaseChatModel:
    if not settings.llm_model:
        raise RuntimeError(
            "LLM_MODEL is not set. Put a model id that your API key can use in .env "
            "(see .env.example)."
        )
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    from langchain_openai import ChatOpenAI  # optional dependency: pip install '.[openai]'

    return ChatOpenAI(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )


def build_embeddings(settings: Settings):
    from langchain_openai import OpenAIEmbeddings  # optional dependency

    return OpenAIEmbeddings(model=settings.embedding_model)


def message_text(message: BaseMessage | str) -> str:
    """Flatten a chat message to plain text (content may be a list of provider blocks)."""
    if isinstance(message, str):
        return message
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)
