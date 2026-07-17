"""Internal runtime metrics without external dependencies."""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
from time import perf_counter


SAFE_NAME = re.compile(r"^[a-z][a-z0-9_:.]{0,63}$")
FORBIDDEN_LABEL_KEYS = {"prompt", "message", "body", "chat_id", "token", "api_key", "secret", "actor", "email", "payload"}
MAX_LABEL_VALUE_LENGTH = 48
MAX_LABELS = 8


@dataclass(frozen=True)
class MetricPoint:
    name: str
    kind: str
    value: float
    labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class MetricsSnapshot:
    points: tuple[MetricPoint, ...]
    created_at: str

    def to_text(self) -> str:
        lines = []
        for point in self.points:
            labels = ",".join(f"{key}={value}" for key, value in point.labels)
            suffix = f" {{{labels}}}" if labels else ""
            lines.append(f"{point.kind} {point.name}={point.value:g}{suffix}")
        return "\n".join(lines)


class MetricsCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._timings: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}

    def increment(self, name: str, amount: float = 1.0, **labels: str) -> None:
        key = (_safe_name(name), _safe_labels(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def gauge(self, name: str, value: float, **labels: str) -> None:
        key = (_safe_name(name), _safe_labels(labels))
        with self._lock:
            self._gauges[key] = float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = (_safe_name(name), _safe_labels(labels))
        with self._lock:
            self._timings.setdefault(key, []).append(float(value))

    def timer(self, name: str, **labels: str) -> "MetricTimer":
        return MetricTimer(self, name, labels)

    def snapshot(self, *, created_at: str = "2026-07-18T00:00:00Z") -> MetricsSnapshot:
        with self._lock:
            points: list[MetricPoint] = []
            for (name, labels), value in sorted(self._counters.items()):
                points.append(MetricPoint(name, "counter", value, labels))
            for (name, labels), value in sorted(self._gauges.items()):
                points.append(MetricPoint(name, "gauge", value, labels))
            for (name, labels), values in sorted(self._timings.items()):
                if values:
                    points.append(MetricPoint(f"{name}.count", "timing", float(len(values)), labels))
                    points.append(MetricPoint(f"{name}.avg", "timing", sum(values) / len(values), labels))
        return MetricsSnapshot(tuple(points), created_at)


class MetricTimer:
    def __init__(self, collector: MetricsCollector, name: str, labels: dict[str, str]) -> None:
        self._collector = collector
        self._name = name
        self._labels = labels
        self._started = 0.0

    def __enter__(self) -> "MetricTimer":
        self._started = perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self._collector.observe(self._name, perf_counter() - self._started, **self._labels)


def _safe_name(name: str) -> str:
    if SAFE_NAME.fullmatch(name) is None:
        raise ValueError("metric name must be a safe bounded component name")
    return name


def _safe_labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    if len(labels) > MAX_LABELS:
        raise ValueError("too many metric labels")
    safe: list[tuple[str, str]] = []
    for key, value in labels.items():
        key = _safe_name(key)
        if key in FORBIDDEN_LABEL_KEYS:
            raise ValueError("forbidden metric label key")
        if len(str(value)) > MAX_LABEL_VALUE_LENGTH:
            raise ValueError("metric label value is too long")
        if not str(value) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,48}", str(value)):
            raise ValueError("metric label value must be bounded and safe")
        safe.append((key, str(value)))
    return tuple(sorted(safe))
