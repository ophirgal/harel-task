"""LLM provider interface and its Anthropic implementation.

The rest of the code depends only on LLMProvider, so supporting another provider means adding one class.
"""

from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    def generate_structured(self, system: str, user: str, output_type: type[T]) -> T:
        """Return the model's answer, parsed and validated as `output_type`."""
        ...


class AnthropicProvider:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "high", max_tokens: int = 16000):
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    def generate_structured(self, system: str, user: str, output_type: type[T]) -> T:
        response = self._client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_type,  # structured output: the response must match this schema
            output_config={"effort": self.effort},
        )
        # Anything other than a normal finish (e.g. "max_tokens" truncation or "refusal") means no usable result.
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            raise RuntimeError(f"LLM returned no valid result (stop_reason={response.stop_reason})")
        return response.parsed_output
