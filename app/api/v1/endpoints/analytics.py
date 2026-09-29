"""
app/api/v1/endpoints/analytics.py
----------------------------------
FastAPI router for claim-scrubbing analytics and KPI reporting.

Endpoints
---------
GET /analytics/metrics – Run the scrubber against all seed claims and
                         return a structured KPI summary suitable for dashboards
                         and denial-management reporting.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from app.models.claim import ClaimInput, ClaimScrubResult, ClaimStatusEnum
from app.services.scrubber import claim_scrubber

router = APIRouter()

# Absolute path to the bundled seed-claims fixture
_SEED_CLAIMS_PATH = Path(__file__).resolve().parents[4] / "app" / "data" / "seed_claims.json"


# ── Helper ────────────────────────────────────────────────────────────────────

def _load_and_scrub_seed_claims() -> List[ClaimScrubResult]:
    """
    Load seed claims from disk, validate them, and run the scrubber over each one.

    Returns
    -------
    List[ClaimScrubResult]
        Ordered list of scrub results matching the seed-claims fixture.

    Raises
    ------
    HTTPException (500)
        If the seed file cannot be read, parsed, or validated.
    """
    if not _SEED_CLAIMS_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seed claims file not found at: {_SEED_CLAIMS_PATH}",
        )

    try:
        raw: list[dict] = json.loads(_SEED_CLAIMS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse seed_claims.json: {exc}",
        ) from exc

    cleaned = [{k: v for k, v in entry.items() if not k.startswith("_")} for entry in raw]

    try:
        claims = [ClaimInput.model_validate(item) for item in cleaned]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Seed claim validation error: {exc}",
        ) from exc

    return [claim_scrubber.scrub_claim(claim) for claim in claims]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get(
    "/metrics",
    status_code=status.HTTP_200_OK,
    summary="Scrubbing KPI metrics report",
    description=(
        "Runs the ClaimGuard scrubber against all bundled seed claims and returns "
        "a structured analytics report covering billed-amount exposure, clean-claim rates, "
        "and a distribution of triggered CARC denial codes. "
        "Ideal for connecting to a BI dashboard or denial-management workflow."
    ),
    tags=["Analytics"],
)
def get_metrics() -> Dict[str, Any]:
    """
    Compute and return scrubbing KPI metrics over the seed claim population.

    KPIs returned
    -------------
    * ``total_claims``             – Number of claims evaluated.
    * ``clean_claims_count``       – Claims with CLEAN status.
    * ``flagged_claims_count``     – Claims with FLAGGED status.
    * ``fatal_error_claims_count`` – Claims with FATAL_ERROR status.
    * ``clean_claim_rate_pct``     – Percentage of clean claims (0–100).
    * ``billed_amount_summary``
        * ``total_billed_usd``     – Sum of all billed charges.
        * ``at_risk_billed_usd``   – Billed amount from FLAGGED + FATAL_ERROR claims.
        * ``clean_billed_usd``     – Billed amount from CLEAN claims.
        * ``at_risk_pct``          – Percentage of total billed that is at risk.
    * ``carc_code_distribution``   – Count of each triggered CARC code across all claims.
    * ``denial_risk_summary``
        * ``average_risk_score``   – Mean denial risk score across all claims.
        * ``max_risk_score``       – Highest individual denial risk score.
        * ``min_risk_score``       – Lowest individual denial risk score.

    Returns
    -------
    dict
        Structured KPI report as a JSON-serialisable dictionary.
    """
    results = _load_and_scrub_seed_claims()

    # ── Status counts ─────────────────────────────────────────────────────────
    total = len(results)
    clean_count = sum(1 for r in results if r.status == ClaimStatusEnum.CLEAN)
    flagged_count = sum(1 for r in results if r.status == ClaimStatusEnum.FLAGGED)
    fatal_count = sum(1 for r in results if r.status == ClaimStatusEnum.FATAL_ERROR)
    clean_rate_pct = round((clean_count / total) * 100, 2) if total else 0.0

    # ── Billed amount exposure ────────────────────────────────────────────────
    total_billed = round(sum(r.billed_amount for r in results), 2)
    at_risk_billed = round(
        sum(
            r.billed_amount
            for r in results
            if r.status in (ClaimStatusEnum.FLAGGED, ClaimStatusEnum.FATAL_ERROR)
        ),
        2,
    )
    clean_billed = round(total_billed - at_risk_billed, 2)
    at_risk_pct = round((at_risk_billed / total_billed) * 100, 2) if total_billed else 0.0

    # ── CARC code distribution ────────────────────────────────────────────────
    carc_counter: Counter = Counter()
    for result in results:
        for carc in result.suggested_carc_codes:
            carc_counter[carc.name] += 1

    carc_distribution = _build_carc_distribution(results, carc_counter)

    # ── Denial risk summary ───────────────────────────────────────────────────
    risk_scores = [r.denial_risk_score for r in results]
    avg_risk = round(sum(risk_scores) / len(risk_scores), 4) if risk_scores else 0.0
    max_risk = max(risk_scores) if risk_scores else 0.0
    min_risk = min(risk_scores) if risk_scores else 0.0

    return {
        "report_title": "ClaimGuard RCM — Scrubbing Analytics Report",
        "claims_evaluated": total,
        "status_breakdown": {
            "clean_claims_count": clean_count,
            "flagged_claims_count": flagged_count,
            "fatal_error_claims_count": fatal_count,
            "clean_claim_rate_pct": clean_rate_pct,
        },
        "billed_amount_summary": {
            "total_billed_usd": total_billed,
            "clean_billed_usd": clean_billed,
            "at_risk_billed_usd": at_risk_billed,
            "at_risk_pct": at_risk_pct,
        },
        "carc_code_distribution": carc_distribution,
        "denial_risk_summary": {
            "average_risk_score": avg_risk,
            "max_risk_score": max_risk,
            "min_risk_score": min_risk,
        },
        "individual_results": [
            {
                "claim_id": r.claim_id,
                "status": r.status.value,
                "denial_risk_score": r.denial_risk_score,
                "billed_amount_usd": r.billed_amount,
                "flags": r.flags,
                "carc_codes": [c.name for c in r.suggested_carc_codes],
            }
            for r in results
        ],
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _carc_description_by_name(name: str) -> str:
    """Return the CARC description for a given enum name, or a fallback string."""
    from app.models.carc_codes import CARCCode  # noqa: PLC0415
    try:
        return CARCCode[name].value
    except KeyError:
        return "Unknown CARC code"


def _build_carc_distribution(
    results: List[ClaimScrubResult],
    carc_counter: Counter,
) -> Dict[str, Any]:
    """
    Build a clean CARC distribution dict with counts and descriptions.

    Parameters
    ----------
    results:
        All scrub results (used to resolve CARC descriptions).
    carc_counter:
        Pre-computed Counter mapping CARC name → occurrence count.

    Returns
    -------
    dict
        Mapping of CARC name → {count, description}.
    """
    from app.models.carc_codes import CARCCode  # noqa: PLC0415

    distribution: Dict[str, Any] = {}
    for code_name, count in sorted(carc_counter.items(), key=lambda x: -x[1]):
        try:
            description = CARCCode[code_name].value
        except KeyError:
            description = "Unknown CARC code"
        distribution[code_name] = {"count": count, "description": description}
    return distribution
