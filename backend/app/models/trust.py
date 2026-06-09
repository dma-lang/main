"""The mandatory trust envelope (F9 / safeguard 3).

Every API value that is AI-derived carries this: a claim label, the source tier, the evidence
reliability score, and the reasoning-chain id for the backlink. The frontend renders it on every
such surface (Mag -> Tier -> Claim -> source -> ERS -> Reason).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import ClaimLabel, SourceTier


class TrustEnvelope(BaseModel):
    claim_label: ClaimLabel
    source_tier: SourceTier | None = None
    ers: float | None = Field(default=None, ge=0.0, le=1.0)
    chain_id: str | None = None  # control.reasoning_chain id (UUID) for the reasoning backlink
