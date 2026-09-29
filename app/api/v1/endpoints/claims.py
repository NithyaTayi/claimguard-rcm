"""
app/api/v1/endpoints/claims.py
-------------------------------
FastAPI router for claim-scrubbing operations.

Endpoints
---------
POST /claims/scrub          – Scrub a single CMS-1500 claim.
POST /claims/scrub/batch    – Scrub a batch of claims and return aggregate KPIs.
GET  /claims/seed-claims    – Retrieve the bundled seed claims from disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, status

from app.models.claim import BatchScrubResponse, ClaimInput, ClaimScrubResult, ClaimStatusEnum
from app.services.scrubber import claim_scrubber

router = APIRouter()

# Absolute path to the bundled seed-claims fixture
_SEED_CLAIMS_PATH = Path(__file__).resolve().parents[4] / "app" / "data" / "seed_claims.json"


# ── Helper ────────────────────────────────────────────────────────────────────

def _load_seed_claims() -> List[ClaimInput]:
    """
    Load and parse seed claims from the JSON fixture file.

    Returns
    -------
    List[ClaimInput]
        Parsed and validated list of seed claim objects.

    Raises
    ------
    HTTPException (500)
        If the file cannot be read or parsed.
    """
    if not _SEED_CLAIMS_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seed claims file not found at path: {_SEED_CLAIMS_PATH}",
        )

    try:
        raw: list[dict] = json.loads(_SEED_CLAIMS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse seed_claims.json: {exc}",
        ) from exc

    # Strip internal _comment keys before Pydantic validation
    cleaned = [{k: v for k, v in entry.items() if not k.startswith("_")} for entry in raw]

    try:
        return [ClaimInput.model_validate(item) for item in cleaned]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seed claim validation error: {exc}",
        ) from exc


def _build_batch_response(results: List[ClaimScrubResult]) -> BatchScrubResponse:
    """
    Compute batch summary KPIs from individual scrub results.

    Parameters
    ----------
    results:
        Ordered list of ``ClaimScrubResult`` objects.

    Returns
    -------
    BatchScrubResponse
        Aggregate summary plus the individual results.
    """
    total = len(results)
    clean_count = sum(1 for r in results if r.status == ClaimStatusEnum.CLEAN)
    flagged_count = total - clean_count
    clean_rate = round(clean_count / total, 4) if total > 0 else 0.0

    return BatchScrubResponse(
        total_claims=total,
        clean_claims_count=clean_count,
        flagged_claims_count=flagged_count,
        clean_claim_rate=clean_rate,
        results=results,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/scrub",
    response_model=ClaimScrubResult,
    status_code=status.HTTP_200_OK,
    summary="Scrub a single claim",
    description=(
        "Submit one CMS-1500-style claim for real-time scrubbing. "
        "Returns a denial-risk score, status classification, human-readable flags, "
        "and suggested CARC codes."
    ),
    tags=["Claims"],
)
def scrub_single_claim(claim: ClaimInput) -> ClaimScrubResult:
    """
    Scrub a single claim and return the verdict.

    Parameters
    ----------
    claim:
        A ``ClaimInput`` JSON body representing one CMS-1500 professional claim.

    Returns
    -------
    ClaimScrubResult
        The complete scrubbing result including status, risk score, flags,
        and suggested CARC codes.
    """
    return claim_scrubber.scrub_claim(claim)


@router.post(
    "/scrub/batch",
    response_model=BatchScrubResponse,
    status_code=status.HTTP_200_OK,
    summary="Scrub a batch of claims",
    description=(
        "Submit a list of CMS-1500-style claims for batch scrubbing. "
        "Returns individual verdicts plus aggregate KPIs (clean claim rate, total counts, etc.)."
    ),
    tags=["Claims"],
)
def scrub_batch_claims(claims: List[ClaimInput]) -> BatchScrubResponse:
    """
    Scrub multiple claims in a single request.

    Parameters
    ----------
    claims:
        A JSON array of ``ClaimInput`` objects. Maximum practical size is ~500 claims
        per request; larger volumes should use chunked requests.

    Returns
    -------
    BatchScrubResponse
        Per-claim verdicts plus batch-level KPI summary.
    """
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The claims list must contain at least one claim.",
        )

    results = [claim_scrubber.scrub_claim(claim) for claim in claims]
    return _build_batch_response(results)


@router.get(
    "/seed-claims",
    response_model=List[ClaimInput],
    status_code=status.HTTP_200_OK,
    summary="Retrieve seed / demo claims",
    description=(
        "Load and return the bundled set of 6 realistic CMS-1500 demo claims "
        "from ``app/data/seed_claims.json``. "
        "Useful for exploring the API without constructing your own payloads."
    ),
    tags=["Claims"],
)
def get_seed_claims() -> List[ClaimInput]:
    """
    Return the bundled demo claims from disk.

    Returns
    -------
    List[ClaimInput]
        Six pre-built claims covering clean, flagged, and fatal-error scenarios.
    """
    return _load_seed_claims()
