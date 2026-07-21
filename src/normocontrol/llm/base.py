"""Typed, non-blocking contracts shared by all LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from normocontrol.errors import NormocontrolError

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class LlmError(NormocontrolError):
    """Base class for sanitized, expected LLM errors."""


class LlmUnavailableError(LlmError):
    """The configured provider cannot currently serve a request."""


class LlmResponseError(LlmError):
    """The provider returned a response that violates the requested contract."""


class LlmRefusalError(LlmResponseError):
    """The model explicitly refused the request."""


class AdvisoryStatus(StrEnum):
    """Non-blocking control-plane outcomes for an LLM invocation."""

    UNVERIFIABLE = "unverifiable"
    SKIPPED = "skipped"


class StrictModel(BaseModel):
    """Immutable public model which rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ChatMessage(StrictModel):
    """One text-only message sent to an OpenAI-compatible endpoint."""

    role: Literal["system", "user", "assistant"]
    content: NonEmptyString


class LlmAdvisory(StrictModel):
    """Safe reason why no blocking LLM result is available."""

    status: AdvisoryStatus
    reason: NonEmptyString


class LlmResult[ResponseT: BaseModel](StrictModel):
    """A validated domain response or a non-blocking advisory, never both."""

    provider: NonEmptyString
    data: ResponseT | None = None
    advisory: LlmAdvisory | None = None

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> LlmResult[ResponseT]:
        if (self.data is None) == (self.advisory is None):
            raise ValueError("exactly one of data or advisory is required")
        return self


class ProbeResult(StrictModel):
    """Capability and model availability reported by ``/models``."""

    provider: NonEmptyString
    available: bool
    model_available: bool = False
    detail: NonEmptyString


class LlmProvider(ABC):
    """Provider interface whose public completion path is always non-blocking."""

    @abstractmethod
    def health_check(self) -> ProbeResult:
        """Probe provider capability without exposing credentials."""

    @abstractmethod
    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        """Return a strict response or raise a sanitized typed error."""

    def complete[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> LlmResult[ResponseT]:
        """Convert every provider failure into an advisory merge-safe result."""
        try:
            return LlmResult(provider=self.name, data=self.request(messages, response_model))
        except LlmError as error:
            return LlmResult(
                provider=self.name,
                advisory=LlmAdvisory(
                    status=AdvisoryStatus.UNVERIFIABLE,
                    reason=str(error),
                ),
            )

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier."""


class FallbackProvider(LlmProvider):
    """Use an explicitly authorized cloud provider after local unavailability."""

    def __init__(
        self,
        primary: LlmProvider,
        cloud: LlmProvider | None,
        *,
        cloud_allowed: bool,
    ) -> None:
        self._primary = primary
        self._cloud = cloud
        self._cloud_allowed = cloud_allowed

    @property
    def name(self) -> str:
        return f"{self._primary.name}+fallback"

    def health_check(self) -> ProbeResult:
        primary = self._primary.health_check()
        if primary.available or not self._cloud_allowed or self._cloud is None:
            return primary
        return self._cloud.health_check()

    def request[ResponseT: BaseModel](
        self,
        messages: tuple[ChatMessage, ...],
        response_model: type[ResponseT],
    ) -> ResponseT:
        try:
            return self._primary.request(messages, response_model)
        except LlmUnavailableError:
            if not self._cloud_allowed:
                raise LlmUnavailableError("cloud fallback is forbidden by policy") from None
            if self._cloud is None:
                raise LlmUnavailableError("cloud fallback is not configured") from None
            return self._cloud.request(messages, response_model)
