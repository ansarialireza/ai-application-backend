import json
from collections.abc import Iterator

import httpx
from django.conf import settings

from .base import (
    GenerationResult,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
)


class OpenAICompatibleProvider:
    supports_streaming = True

    def __init__(self):
        self.base_url = settings.AI_PROVIDER_API_BASE_URL.rstrip("/")
        self.api_key = settings.AI_PROVIDER_API_KEY
        self.timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS

    def _check_config(self):
        if not self.api_key:
            raise ProviderNotConfigured("The configured AI provider has no API key.")
        if not self.base_url.startswith(("https://", "http://")):
            raise ProviderNotConfigured("The configured AI provider URL is invalid.")

    def _payload(self, model, messages, temperature, max_tokens, stream=False):
        return {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    @staticmethod
    def _usage(payload, field):
        usage = payload.get("usage")
        value = usage.get(field) if isinstance(usage, dict) else None
        return value if isinstance(value, int) and value >= 0 else None

    def generate(self, model, messages, temperature, max_tokens):
        self._check_config()
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=self._payload(model, messages, temperature, max_tokens),
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("The AI provider request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("The AI provider could not be reached.") from exc
        if response.is_error:
            raise ProviderRejected(
                f"The AI provider rejected the request (HTTP {response.status_code}).",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            payload = response.json()
            choices = payload["choices"]
            content = choices[0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderResponseError("The AI provider returned an invalid completion response.") from exc
        return GenerationResult(
            content=content,
            prompt_tokens=self._usage(payload, "prompt_tokens"),
            completion_tokens=self._usage(payload, "completion_tokens"),
        )

    def stream(self, model, messages, temperature, max_tokens) -> Iterator[str]:
        self._check_config()
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream"},
                json=self._payload(model, messages, temperature, max_tokens, stream=True),
                timeout=self.timeout,
            ) as response:
                if response.is_error:
                    raise ProviderRejected(
                        f"The AI provider rejected the stream (HTTP {response.status_code}).",
                        retryable=response.status_code == 429 or response.status_code >= 500,
                    )
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                        delta = event["choices"][0]["delta"].get("content", "")
                        if isinstance(delta, str) and delta:
                            yield delta
                    except (ValueError, TypeError, KeyError, IndexError) as exc:
                        raise ProviderResponseError("The AI provider returned an invalid stream event.") from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("The AI provider stream timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("The AI provider stream could not be reached.") from exc
