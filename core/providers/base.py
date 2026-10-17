from dataclasses import dataclass
from typing import Iterable, Protocol

from core.exceptions import ServiceError


@dataclass(frozen=True)
class GenerationResult:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ProviderError(ServiceError):
    code = "provider_error"
    status_code = 502


class ProviderNotConfigured(ProviderError):
    code = "provider_not_configured"
    status_code = 503


class ProviderTimeout(ProviderError):
    code = "provider_timeout"
    status_code = 504
    retryable = True


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderRejected(ProviderError):
    code = "provider_rejected"

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class ProviderResponseError(ProviderError):
    code = "provider_invalid_response"


class ChatProvider(Protocol):
    supports_streaming: bool

    def generate(self, model: str, messages: list[dict], temperature: float, max_tokens: int) -> GenerationResult: ...

    def stream(self, model: str, messages: list[dict], temperature: float, max_tokens: int) -> Iterable[str]: ...
