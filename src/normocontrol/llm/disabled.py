"""Explicitly disabled LLM provider."""

from __future__ import annotations

from pydantic import BaseModel

from normocontrol.llm.base import (
    AdvisoryStatus,
    ChatMessage,
    LlmAdvisory,
    LlmProvider,
    LlmResult,
    LlmUnavailableError,
    ProbeResult,
)


class DisabledProvider(LlmProvider):
    """A deterministic provider that never performs I/O."""

    @property
    def name(self) -> str:
        return "disabled"

    def health_check(self) -> ProbeResult:
        return ProbeResult(
            provider=self.name,
            available=False,
            detail="LLM is disabled by configuration",
        )

    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        del messages, response_model
        raise LlmUnavailableError("LLM is disabled by configuration")

    def complete[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> LlmResult[ResponseT]:
        del messages, response_model
        return LlmResult(
            provider=self.name,
            advisory=LlmAdvisory(
                status=AdvisoryStatus.SKIPPED,
                reason="LLM is disabled by configuration",
            ),
        )


def disabled_result(response_model: type[BaseModel]) -> LlmResult[BaseModel]:
    """Build a typed skipped result for orchestration code without an instance."""
    return DisabledProvider().complete((), response_model)
