"""Strategy parameter schemas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ParameterType(str, Enum):
    """Supported strategy parameter types."""

    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class ParameterDefinition:
    """Definition for one strategy parameter."""

    name: str
    parameter_type: ParameterType
    default: Any
    min_value: float | int | None = None
    max_value: float | int | None = None
    description: str = ""

    def validate(self, value: Any) -> None:
        if not self.name:
            raise ValueError("parameter name is required")
        if not _matches_type(value, self.parameter_type):
            raise ValueError(f"{self.name} must be {self.parameter_type.value}")
        if self.min_value is not None and value < self.min_value:
            raise ValueError(f"{self.name} must be >= {self.min_value}")
        if self.max_value is not None and value > self.max_value:
            raise ValueError(f"{self.name} must be <= {self.max_value}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameter_type": self.parameter_type.value,
            "default": self.default,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParameterDefinition":
        return cls(
            name=str(data["name"]),
            parameter_type=ParameterType(str(data["parameter_type"])),
            default=data["default"],
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True)
class ParameterSchema:
    """Collection of parameter definitions."""

    definitions: tuple[ParameterDefinition, ...]

    def defaults(self) -> dict[str, Any]:
        return {definition.name: definition.default for definition in self.definitions}

    def validate(self, values: dict[str, Any]) -> dict[str, Any]:
        merged = self.defaults()
        unknown = set(values) - {definition.name for definition in self.definitions}
        if unknown:
            raise ValueError(f"unknown parameters: {tuple(sorted(unknown))}")
        merged.update(values)
        for definition in self.definitions:
            definition.validate(merged[definition.name])
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {"definitions": [definition.to_dict() for definition in self.definitions]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParameterSchema":
        return cls(
            definitions=tuple(ParameterDefinition.from_dict(item) for item in data.get("definitions", []))
        )


def _matches_type(value: Any, parameter_type: ParameterType) -> bool:
    if parameter_type is ParameterType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if parameter_type is ParameterType.FLOAT:
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if parameter_type is ParameterType.STRING:
        return isinstance(value, str)
    if parameter_type is ParameterType.BOOLEAN:
        return isinstance(value, bool)
    return False

