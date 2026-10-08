"""Scriptable stand-ins used by the test-suite and by ``eval --oracle`` (no API key needed)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .db import QueryPlan, QueryResult, WarehouseError
from .llm import message_text


class FunctionChatModel(BaseChatModel):
    """A chat model whose reply is ``fn(prompt_text)``; prompts carry a ``[task: ...]`` tag."""

    fn: Callable[[str], str]

    @property
    def _llm_type(self) -> str:
        return "function-fake"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any):
        prompt = "\n\n".join(message_text(m) for m in messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.fn(prompt)))])


class FakeWarehouse:
    """In-memory warehouse: ``explain``/``execute`` are driven by simple callables."""

    def __init__(
        self,
        explain: Callable[[str], QueryPlan] | None = None,
        execute: Callable[[str], QueryResult] | None = None,
    ):
        self._explain = explain or (lambda sql: QueryPlan(total_cost=10.0, plan_rows=1))
        self._execute = execute or (lambda sql: QueryResult(columns=["n"], rows=[[1]]))
        self.executed: list[str] = []

    def explain(self, sql: str) -> QueryPlan:
        return self._explain(sql)

    def execute(self, sql: str) -> QueryResult:
        self.executed.append(sql)
        return self._execute(sql)


__all__ = ["FakeWarehouse", "FunctionChatModel", "WarehouseError"]
