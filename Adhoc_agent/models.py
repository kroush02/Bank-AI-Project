"""Typed contracts between agents; model responses are untrusted inputs."""

import math
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowError(Exception):
    """A safe-to-display workflow failure."""


class ClarificationRequired(WorkflowError):
    pass


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$", max_length=64)
    kind: Literal["text", "integer", "real", "null"]
    value: str = Field(max_length=2000)

    def converted(self):
        if self.kind == "integer":
            if not re.fullmatch(r"-?\d+", self.value):
                raise WorkflowError("Invalid integer parameter.")
            number = int(self.value)
            if not -(2**63) <= number < 2**63:
                raise WorkflowError("Integer parameter exceeds SQLite range.")
            return number
        if self.kind == "real":
            try:
                number = float(self.value)
            except ValueError as exc:
                raise WorkflowError("Invalid numeric parameter.") from exc
            if not math.isfinite(number):
                raise WorkflowError("Non-finite numeric parameter.")
            return number
        if self.kind == "null":
            return None
        return self.value


class SQLPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sql: str = Field(max_length=12000)
    parameters: list[Binding] = Field(max_length=50)
    explanation: str = Field(max_length=3000)
    clarification: str = Field(max_length=2000)

    def bindings(self) -> dict:
        names = [p.name for p in self.parameters]
        if len(names) != len(set(names)):
            raise WorkflowError("Duplicate parameter names.")
        return {p.name: p.converted() for p in self.parameters}


class SemanticReview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approved: bool
    reason: str = Field(min_length=1, max_length=3000)


@dataclass(frozen=True)
class Ticket:
    id: str
    request: str


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]


@dataclass(frozen=True)
class ValidationReceipt:
    plan: SQLPlan
    reason: str


@dataclass(frozen=True)
class WorkflowResult:
    ticket_id: str
    status: str
    report_path: str | None = None
    error: str | None = None
