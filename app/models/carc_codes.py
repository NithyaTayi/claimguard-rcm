"""
app/models/carc_codes.py
------------------------
Claim Adjustment Reason Codes (CARCs) as defined by the CAQH CORE / X12 standard.
These codes appear on Electronic Remittance Advice (ERA/835) transactions and
indicate why a claim or service line was adjusted.

Reference: https://www.wpc-edi.com/reference/codelists/healthcare/claim-adjustment-reason-codes/
"""

from __future__ import annotations

from enum import Enum


class CARCCode(str, Enum):
    """
    Subset of Claim Adjustment Reason Codes (CARCs) most commonly encountered
    in outpatient and surgical billing scenarios.

    Each member's *value* is the human-readable CMS description, making it
    safe to serialise directly to JSON for downstream consumption by billing
    staff or denial-management platforms.
    """

    CO_4 = "The procedure code is inconsistent with the modifier used or a required modifier is missing."
    CO_11 = "The diagnosis is inconsistent with the procedure."
    CO_16 = "Claim/service lacks information or has submission/billing error(s)."
    CO_18 = "Exact duplicate claim/service."
    CO_197 = "Precertification/authorization/notification/pre-treatment absent."

    # ── Convenience helpers ──────────────────────────────────────────────────

    @classmethod
    def from_key(cls, key: str) -> "CARCCode":
        """
        Look up a CARCCode by its enum *name* (e.g. ``"CO_16"``).

        Raises
        ------
        KeyError
            If the supplied key does not match any defined CARC code.
        """
        try:
            return cls[key]
        except KeyError as exc:
            raise KeyError(
                f"'{key}' is not a recognised CARC code key. "
                f"Valid keys: {[m.name for m in cls]}"
            ) from exc

    @property
    def code_number(self) -> str:
        """Return the numeric portion of the CARC code (e.g. ``'16'`` for CO_16)."""
        return self.name.split("_", 1)[1]

    def __str__(self) -> str:  # noqa: D105
        return f"{self.name}: {self.value}"
