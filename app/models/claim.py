"""
app/models/claim.py
-------------------
Pydantic v2 request / response schemas for the ClaimGuard RCM scrubbing API.

Schema hierarchy
----------------
ClaimInput          – Inbound CMS-1500-style claim payload
ClaimStatusEnum     – CLEAN / FLAGGED / FATAL_ERROR classification
ClaimScrubResult    – Scrubbing verdict for a single claim
BatchScrubResponse  – Aggregate response for /scrub/batch
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.carc_codes import CARCCode


# ── Status Classification ────────────────────────────────────────────────────

class ClaimStatusEnum(str, Enum):
    """
    Describes the overall scrubbing verdict for a single claim.

    CLEAN       – No issues detected; claim is ready for submission.
    FLAGGED     – One non-critical issue found; human review recommended.
    FATAL_ERROR – Two or more issues, or a critical billing error (e.g. bad NPI).
                  Claim must NOT be submitted until resolved.
    """

    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"
    FATAL_ERROR = "FATAL_ERROR"


# ── Input Schema ─────────────────────────────────────────────────────────────

class ClaimInput(BaseModel):
    """
    Represents a single CMS-1500 professional claim submitted for scrubbing.

    All string fields are stripped of leading/trailing whitespace on ingest.
    """

    claim_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique claim identifier (internal or payer-assigned).",
        examples=["CLM-2024-001"],
    )
    patient_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique patient / member identifier.",
        examples=["PAT-10042"],
    )
    payer_id: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Payer / insurance plan identifier (e.g. '00192' for Medicare).",
        examples=["00192"],
    )
    provider_npi: str = Field(
        ...,
        min_length=10,
        max_length=10,
        description="Rendering provider National Provider Identifier (NPI). Must be 10 digits.",
        examples=["1234567893"],
    )
    diagnosis_codes: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list of ICD-10-CM diagnosis codes. "
            "The first entry is treated as the primary (principal) diagnosis."
        ),
        examples=[["M17.11", "Z96.641"]],
    )
    procedure_codes: List[str] = Field(
        ...,
        description=(
            "Ordered list of CPT / HCPCS Level II procedure codes billed on this claim."
        ),
        examples=[["27447", "99213"]],
    )
    billed_amount: float = Field(
        ...,
        gt=0.0,
        description="Total charge billed to the payer in USD (must be positive).",
        examples=[15750.00],
    )
    prior_auth_number: Optional[str] = Field(
        default=None,
        max_length=32,
        description=(
            "Pre-authorization / pre-certification number issued by the payer. "
            "Required for high-cost surgical procedures."
        ),
        examples=["AUTH-2024-88421"],
    )
    service_date: str = Field(
        ...,
        description="Date of service in ISO-8601 format (YYYY-MM-DD).",
        examples=["2024-03-15"],
    )

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("claim_id", "patient_id", "payer_id", "provider_npi", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        """Strip whitespace from all top-level string identifiers."""
        return v.strip() if isinstance(v, str) else v

    @field_validator("provider_npi")
    @classmethod
    def npi_must_be_digits(cls, v: str) -> str:
        """NPI must consist solely of 10 decimal digits."""
        if not v.isdigit():
            raise ValueError("provider_npi must contain exactly 10 digits (no letters or symbols).")
        return v

    @field_validator("service_date")
    @classmethod
    def validate_service_date_format(cls, v: str) -> str:
        """Ensure date follows YYYY-MM-DD ISO format."""
        from datetime import datetime  # noqa: PLC0415
        try:
            datetime.strptime(v.strip(), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"service_date '{v}' is not a valid ISO-8601 date (expected YYYY-MM-DD)."
            ) from exc
        return v.strip()

    model_config = {"str_strip_whitespace": True}


# ── Output Schemas ────────────────────────────────────────────────────────────

class ClaimScrubResult(BaseModel):
    """
    The scrubbing verdict returned for a single claim.

    Fields
    ------
    claim_id            – Echo of the submitted claim identifier.
    status              – CLEAN / FLAGGED / FATAL_ERROR classification.
    denial_risk_score   – Probability estimate [0.0, 1.0] that the claim will be denied.
    flags               – Human-readable descriptions of each detected issue.
    suggested_carc_codes – X12 CARC codes anticipated on the ERA if denied unchanged.
    billed_amount       – Echo of the submitted billed amount (USD).
    """

    claim_id: str = Field(..., description="Echo of the submitted claim identifier.")
    status: ClaimStatusEnum = Field(..., description="Scrubbing verdict classification.")
    denial_risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Denial probability estimate between 0.0 (low risk) and 1.0 (near-certain denial).",
    )
    flags: List[str] = Field(
        default_factory=list,
        description="Ordered list of human-readable issue descriptions identified during scrubbing.",
    )
    suggested_carc_codes: List[CARCCode] = Field(
        default_factory=list,
        description=(
            "CARC codes the payer is likely to return on the ERA (835) "
            "if the claim is submitted without correction."
        ),
    )
    billed_amount: float = Field(..., description="Total charge billed to payer (USD).")


class BatchScrubResponse(BaseModel):
    """
    Aggregate response returned by the POST /scrub/batch endpoint.

    Provides summary KPIs alongside individual scrub results for all submitted claims.
    """

    total_claims: int = Field(..., description="Total number of claims processed in this batch.")
    clean_claims_count: int = Field(..., description="Number of claims classified as CLEAN.")
    flagged_claims_count: int = Field(
        ...,
        description="Number of claims classified as FLAGGED or FATAL_ERROR.",
    )
    clean_claim_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Proportion of clean claims as a decimal (e.g. 0.75 = 75%).",
    )
    results: List[ClaimScrubResult] = Field(
        ...,
        description="Individual scrub results for every claim in the batch, in submission order.",
    )
