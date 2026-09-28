"""Error codes and findings.

Every problem the framework reports is a machine-readable `Finding` with a
stable uppercase `code`. Callers (future workflows) branch on the code, never
on the message text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- boundary / dependency -------------------------------------------------
BOUNDARY_VIOLATION = "BOUNDARY_VIOLATION"
ILLEGAL_DEPENDENCY = "ILLEGAL_DEPENDENCY"

# --- "the metadata cannot answer this, and reading code is not allowed" ----
CONTRACT_INSUFFICIENT = "CONTRACT_INSUFFICIENT"
UNITEMISED_USES = "UNITEMISED_USES"
ARCHITECTURE_CHANGE_REQUIRED = "ARCHITECTURE_CHANGE_REQUIRED"

# --- load / structure errors ----------------------------------------------
INVALID_METADATA = "INVALID_METADATA"
UNKNOWN_MODULE = "UNKNOWN_MODULE"
UNKNOWN_CONTRACT = "UNKNOWN_CONTRACT"
CYCLE_DETECTED = "CYCLE_DETECTED"

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"


@dataclass(frozen=True)
class Finding:
    """One machine-readable result."""

    code: str
    message: str
    severity: str = ERROR
    # Free-form, JSON-serialisable context. Must never contain file contents.
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "context": self.context,
        }

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code}: {self.message}"


class ArchError(Exception):
    """Raised when the architecture metadata itself cannot be loaded."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class ContractInsufficient(ArchError):
    """The declared contracts do not describe what a consumer needs.

    Raised instead of falling back to reading another module's implementation.
    """

    def __init__(self, message: str, code: str = CONTRACT_INSUFFICIENT):
        super().__init__(code, message)
