from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FrameworkError(Exception):
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.context:
            return f"[{self.code}] {self.message}"
        context_bits = ", ".join(
            f"{key}={value}" for key, value in sorted(self.context.items())
        )
        return f"[{self.code}] {self.message} ({context_bits})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


class InputValidationError(FrameworkError):
    pass


class ConfigurationError(FrameworkError):
    pass


class StageExecutionError(FrameworkError):
    pass


class RetrievalError(FrameworkError):
    pass


class SessionStateError(FrameworkError):
    pass
