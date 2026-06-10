"""Benchmark scouting intelligence — the D4 ingest + adversarial stages (spec §D4).

Live shape (monthly Batch, through the single Gemini facade): grounded fetch of curated public
benchmark datasets (T2, D6 public-sources-only) -> per-benchmark ADVERSARIAL review on the pinned
synthesis/adversarial model ("argues the opposite, surfaces missing evidence and overreach") whose
verdict chip is BENCHMARK / INDICATIVE / EXPLORATORY. Hermetic mode replays this module's recorded
fixture (real-shaped curated datasets + the recorded adversary verdicts, VCR style) so the
identical downstream CI -> map -> gate -> persist pipeline runs deterministically with zero spend.
The service layer (services/benchmarks.py) consumes the same two contracts live mode produces.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.gemini import Gemini
from app.settings import get_settings


@dataclass(frozen=True)
class RawBenchmark:
    """One curated benchmark dataset, before CI computation or adversarial review."""

    source: str
    tier: str  # curated benchmark datasets are T2 (source registry)
    url: str
    published: str  # ISO date
    metric: str
    unit: str
    segment: str  # subvertical the panel covers
    observations: tuple[float, ...]  # the raw data points
    methodology: str | None  # None renders "not documented" — never invented
    specificity: float  # directness of the metric for ERS
    topics: str  # meaning-probe terms retrieval maps the catalogue with


@dataclass(frozen=True)
class AdversaryVerdict:
    """The adversarial review of one benchmark claim: did the thesis survive? ``verdict`` is the
    chip (BENCHMARK survives · INDICATIVE survives with caveats · EXPLORATORY does not support a
    band); ``note`` is the recorded critique, kept verbatim in the reasoning chain."""

    verdict: str
    note: str
    model: str


# The recorded fixture: curated, real-shaped public benchmark panels for the catalogue's
# subverticals. Two entries prove the honesty rails end-to-end: the GenAI model-risk panel is
# THIN (4 observations, under the configured floor -> coverage-gap banner, CI suppressed, the
# adversary refuses a band) and the fraud panel has NO methodology (renders "not documented").
_FIXTURE: tuple[tuple[RawBenchmark, AdversaryVerdict], ...] = (
    (
        RawBenchmark(
            source="Celent digital banking panel",
            tier="T2",
            url="https://www.celent.com/insights",
            published="2026-05-02",
            metric="Digital self-service deflection rate",
            unit="%",
            segment="BK",
            observations=(
                14.0,
                16.5,
                17.2,
                18.0,
                18.8,
                19.5,
                20.1,
                20.6,
                21.0,
                21.4,
                21.9,
                22.3,
                22.8,
                23.1,
                23.7,
                24.2,
                24.9,
                25.5,
                26.2,
                27.0,
                28.1,
                29.4,
                31.0,
                33.5,
            ),
            methodology=(
                "24 retail banks (NA/EU), FY2025 reported contact volumes; deflection = "
                "sessions resolved in self-service / total assisted-eligible sessions, "
                "normalised for channel mix."
            ),
            specificity=0.85,
            topics="self-service deflection virtual agent assistant",
        ),
        AdversaryVerdict(
            verdict="BENCHMARK",
            note=(
                "Thesis survives adversarial review: 24 independent observations, tight "
                "interquartile range, methodology normalises channel mix — the claim does not "
                "overreach the band."
            ),
            model="hermetic-stub",
        ),
    ),
    (
        RawBenchmark(
            source="FS-ISAC fraud benchmark consortium",
            tier="T2",
            url="https://www.fsisac.com/",
            published="2026-04-15",
            metric="Card-fraud false-positive ratio",
            unit=": 1",
            segment="BK",
            observations=(
                5.2,
                6.1,
                6.8,
                7.4,
                7.9,
                8.3,
                8.8,
                9.2,
                9.7,
                10.3,
                11.0,
                11.8,
                12.7,
                13.9,
                15.4,
                17.2,
                19.5,
                22.4,
            ),
            methodology=None,  # consortium shares the panel, not the computation — never invented
            specificity=0.8,
            topics="fraud risk scoring detection false positive",
        ),
        AdversaryVerdict(
            verdict="INDICATIVE",
            note=(
                "Critique: the consortium does not publish its computation method, so the "
                "distribution is directional — usable for orientation, not for a defensible "
                "client-facing claim."
            ),
            model="hermetic-stub",
        ),
    ),
    (
        RawBenchmark(
            source="McKinsey Panorama SME lending panel",
            tier="T2",
            url="https://www.mckinsey.com/industries/financial-services",
            published="2026-03-20",
            metric="SME credit time-to-decision",
            unit="days",
            segment="CL",
            observations=(0.5, 1.0, 2.0, 3.0, 4.5, 6.0, 8.0, 10.0, 14.0, 18.0, 24.0, 32.0),
            methodology=(
                "12 SME lenders, application-to-decision elapsed days at the median application; "
                "digital-native and incumbent lenders pooled."
            ),
            specificity=0.75,
            topics="automated credit decisioning underwriting",
        ),
        AdversaryVerdict(
            verdict="INDICATIVE",
            note=(
                "Critique: the panel pools digital-native and incumbent lenders, so the spread "
                "reflects segment mix as much as capability — present the band with that caveat."
            ),
            model="hermetic-stub",
        ),
    ),
    (
        RawBenchmark(
            source="Gartner AI governance pulse",
            tier="T2",
            url="https://www.gartner.com/en/industries/banking",
            published="2026-05-26",
            metric="GenAI model-risk review cycle time",
            unit="weeks",
            segment="BK",
            observations=(3.0, 5.0, 9.0, 14.0),
            methodology="Pulse survey, self-reported cycle times; small early-adopter sample.",
            specificity=0.6,
            topics="AI model risk management governance validation monitoring",
        ),
        AdversaryVerdict(
            verdict="EXPLORATORY",
            note=(
                "Critique: four self-reported observations cannot support a confidence band — "
                "treat as exploratory colour only; no client-facing precision."
            ),
            model="hermetic-stub",
        ),
    ),
)

_RECORDED: dict[str, AdversaryVerdict] = {raw.metric: verdict for raw, verdict in _FIXTURE}


async def fetch_benchmarks() -> list[RawBenchmark]:
    """Ingest stage. Hermetic: the recorded fixture; live: the monthly grounded Batch fetch of
    curated public datasets through the one Gemini wrapper (raises until Stage 4 wires Vertex)."""
    if get_settings().is_hermetic:
        return [raw for raw, _ in _FIXTURE]
    return await Gemini().fetch_benchmarks()


async def adversary_review(raw: RawBenchmark) -> AdversaryVerdict:
    """Adversarial stage. Hermetic: the recorded verdict for the fixture benchmark (closed world —
    an unknown metric is a wiring bug, not a fallback); live: the pinned adversarial model. A live
    429/timeout returns no verdict and the read model renders "pending" — never a made-up chip."""
    if get_settings().is_hermetic:
        try:
            return _RECORDED[raw.metric]
        except KeyError:
            raise LookupError(f"no recorded verdict for {raw.metric!r}") from None
    return await Gemini().adversary_review(raw)
