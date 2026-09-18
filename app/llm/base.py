"""Abstract LLM provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResult:
    """Raw structured output from an LLM call.

    The result is **untrusted**. The deterministic guardrails are responsible
    for validating every field before the optimizer ever sees it.
    """

    raw_text: str
    parsed: dict[str, Any]


class LLMProvider(ABC):
    """Implementations translate operator notes into a structured directive list.

    The contract is intentionally narrow: the LLM must return a JSON object
    of the form ``{"directives": [...]}`` where each entry corresponds to one
    operator note in note_index order.
    """

    @abstractmethod
    def interpret_notes(self, operator_notes: list[str]) -> LLMResult:
        """Send the operator notes to the LLM and return its raw structured output.

        Implementations MUST:
        * Return one entry per input note, in note_index order.
        * Use ``no_op`` with ``applies=false`` for irrelevant notes.
        * Never invent unsupported directive types.
        * Use whole-hour semantics with start-inclusive / end-exclusive windows.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the underlying model, for logging and the README."""
