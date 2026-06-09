"""API enums mirroring the shared DB enums (values serialize to the Postgres enum labels)."""

from __future__ import annotations

from enum import StrEnum


class ClaimLabel(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    CEILING_ESTIMATE = "CEILING_ESTIMATE"


class SourceTier(StrEnum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"


class Magnitude(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class LifecycleState(StrEnum):
    EMERGING = "emerging"
    RISING = "rising"
    STABLE = "stable"
    DECLINING = "declining"
    FADING = "fading"
    DEAD = "dead"
