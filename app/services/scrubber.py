"""
app/services/scrubber.py
------------------------
ClaimScrubber: the core claim-scrubbing and denial-risk prediction engine.

Architecture notes
------------------
* Each check method is intentionally *pure with side effects via mutable
  accumulator lists* – this keeps the public API simple while allowing the
  ``scrub_claim`` orchestrator to collect flags and CARC codes in a single pass.
* The NPI Luhn check follows the CMS specification:
    1. Prepend the constant prefix ``80840`` to the 10-digit NPI.
    2. Run the standard Luhn algorithm over the resulting 15-digit number.
    3. The check digit (last digit of the original NPI) must satisfy the Luhn sum.
* All public methods are stateless and thread-safe; no instance state is mutated
  between calls, making this class safe to use as a FastAPI dependency singleton.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from app.models.carc_codes import CARCCode
from app.models.claim import ClaimInput, ClaimScrubResult, ClaimStatusEnum


# ── Constants ────────────────────────────────────────────────────────────────

# CPT codes that always require prior authorisation from most commercial payers
# and Medicare Advantage plans before the procedure is performed.
_PRIOR_AUTH_REQUIRED_CPTS: frozenset[str] = frozenset(
    ["27447", "43239", "66984", "99223", "33533"]
)

# Evaluation & Management codes that require a matching, valid diagnosis
_EM_CODES_REQUIRING_DX: frozenset[str] = frozenset(["99213", "99214"])

# ICD-10-CM code pattern: single alpha character + 2 digits + optional decimal
# sub-classification up to 4 additional digits.
_ICD10_PATTERN: re.Pattern[str] = re.compile(
    r"^[A-Z][0-9]{2}(\.[0-9]{1,4})?$",
    re.IGNORECASE,
)

# CMS Luhn prefix prepended to the 10-digit NPI before checksum validation.
_NPI_LUHN_PREFIX: str = "80840"


# ── Scrubber Class ────────────────────────────────────────────────────────────

class ClaimScrubber:
    """
    Stateless claim-scrubbing engine implementing CMS billing-validation rules.

    Usage
    -----
    >>> scrubber = ClaimScrubber()
    >>> result = scrubber.scrub_claim(claim_input)
    """

    # ── NPI Validation ────────────────────────────────────────────────────────

    @staticmethod
    def _luhn_check(number: str) -> bool:
        """
        Standard Luhn algorithm implementation.

        Parameters
        ----------
        number:
            String of digits to validate. The *last* digit is the check digit.

        Returns
        -------
        bool
            ``True`` if the number passes the Luhn check, ``False`` otherwise.
        """
        total = 0
        reverse_digits = number[::-1]
        for idx, ch in enumerate(reverse_digits):
            digit = int(ch)
            if idx % 2 == 1:          # every second digit from the right (0-indexed)
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        return total % 10 == 0

    def validate_npi(
        self,
        npi: str,
        flags: List[str],
        carc_codes: List[CARCCode],
    ) -> bool:
        """
        Validate a National Provider Identifier (NPI) against CMS rules.

        Validation steps
        ----------------
        1. Must be exactly 10 decimal digits.
        2. First digit must be ``'1'`` (Type-1 / individual) or ``'2'`` (Type-2 / organisation).
        3. The full NPI must pass the CMS Luhn check (prefix ``80840`` + NPI).

        Parameters
        ----------
        npi:
            The raw NPI string from the claim.
        flags:
            Mutable list of flag messages; failure messages are appended here.
        carc_codes:
            Mutable list of CARCCode values; ``CO_16`` is appended on failure.

        Returns
        -------
        bool
            ``True`` if the NPI is valid, ``False`` otherwise.
        """
        # ── Basic structural checks ──────────────────────────────────────────
        if not npi.isdigit() or len(npi) != 10:
            flags.append(
                f"Invalid Provider NPI format: '{npi}' must be exactly 10 digits."
            )
            if CARCCode.CO_16 not in carc_codes:
                carc_codes.append(CARCCode.CO_16)
            return False

        # ── Type indicator check ────────────────────────────────────────────
        if npi[0] not in ("1", "2"):
            flags.append(
                f"Invalid Provider NPI type indicator: '{npi[0]}' "
                "– NPI must begin with '1' (individual) or '2' (organisation)."
            )
            if CARCCode.CO_16 not in carc_codes:
                carc_codes.append(CARCCode.CO_16)
            return False

        # ── CMS Luhn check (prefix 80840 + NPI) ────────────────────────────
        luhn_input = _NPI_LUHN_PREFIX + npi
        if not self._luhn_check(luhn_input):
            flags.append(
                f"Invalid Provider NPI checksum: '{npi}' fails the CMS Luhn validation "
                "(prefix 80840 applied per CMS NPI Final Rule)."
            )
            if CARCCode.CO_16 not in carc_codes:
                carc_codes.append(CARCCode.CO_16)
            return False

        return True

    # ── Prior Authorization Check ─────────────────────────────────────────────

    def check_prior_auth(
        self,
        claim: ClaimInput,
        flags: List[str],
        carc_codes: List[CARCCode],
    ) -> bool:
        """
        Determine whether prior authorisation is required but absent.

        A missing prior-auth number is flagged when the claim contains at least
        one CPT code from the high-cost / surgical authorisation-required set AND
        ``prior_auth_number`` is ``None`` or blank.

        Parameters
        ----------
        claim:
            The inbound claim payload.
        flags:
            Mutable list of flag messages; a failure message is appended here.
        carc_codes:
            Mutable list of CARCCode values; ``CO_197`` is appended on failure.

        Returns
        -------
        bool
            ``True`` if the claim passes (no issue found), ``False`` if flagged.
        """
        requiring_auth = [
            cpt
            for cpt in claim.procedure_codes
            if cpt.strip() in _PRIOR_AUTH_REQUIRED_CPTS
        ]

        if not requiring_auth:
            return True  # no auth-required CPTs on this claim

        auth_absent = (
            claim.prior_auth_number is None
            or claim.prior_auth_number.strip() == ""
        )

        if auth_absent:
            flags.append(
                f"Missing required prior-authorization for surgical CPT(s): "
                f"{', '.join(requiring_auth)}. "
                "A valid prior_auth_number must be supplied before claim submission."
            )
            if CARCCode.CO_197 not in carc_codes:
                carc_codes.append(CARCCode.CO_197)
            return False

        return True

    # ── Coding Consistency Check ──────────────────────────────────────────────

    def check_coding_consistency(
        self,
        claim: ClaimInput,
        flags: List[str],
        carc_codes: List[CARCCode],
    ) -> bool:
        """
        Validate ICD-10 / CPT coding consistency rules.

        Rules applied
        -------------
        1. At least one ``diagnosis_codes`` entry must match the ICD-10-CM pattern.
        2. ``procedure_codes`` must not be empty.
        3. If an E&M CPT (99213/99214) is billed, the primary diagnosis must be a
           valid ICD-10-CM code (catches missing or malformed DX + EM bundles).

        Parameters
        ----------
        claim:
            The inbound claim payload.
        flags:
            Mutable list of flag messages; failure messages are appended here.
        carc_codes:
            Mutable list of CARCCode values; relevant codes are appended on failure.

        Returns
        -------
        bool
            ``True`` if no coding issues were found, ``False`` otherwise.
        """
        passed = True

        # ── Rule 1: primary diagnosis must be valid ICD-10-CM ────────────────
        valid_dx_codes = [
            dx for dx in claim.diagnosis_codes
            if _ICD10_PATTERN.match(dx.strip())
        ]

        if not valid_dx_codes:
            flags.append(
                "No valid ICD-10-CM diagnosis code found. "
                f"Submitted codes: {claim.diagnosis_codes}. "
                "Codes must match the pattern [A-Z][0-9]{{2}}(\\.[0-9]{{1,4}})?."
            )
            if CARCCode.CO_16 not in carc_codes:
                carc_codes.append(CARCCode.CO_16)
            passed = False

        # ── Rule 2: at least one procedure code must exist ───────────────────
        if not claim.procedure_codes:
            flags.append(
                "No procedure codes (CPT/HCPCS) were found on this claim. "
                "At least one procedure code is required for claim adjudication."
            )
            if CARCCode.CO_16 not in carc_codes:
                carc_codes.append(CARCCode.CO_16)
            passed = False

        # ── Rule 3: E&M codes must have a valid primary diagnosis ────────────
        em_cpts_present = [
            cpt for cpt in claim.procedure_codes
            if cpt.strip() in _EM_CODES_REQUIRING_DX
        ]

        if em_cpts_present:
            primary_dx = claim.diagnosis_codes[0].strip() if claim.diagnosis_codes else ""
            if not primary_dx or not _ICD10_PATTERN.match(primary_dx):
                flags.append(
                    f"E&M procedure code(s) {em_cpts_present} require a valid primary "
                    f"ICD-10-CM diagnosis. Found primary diagnosis: '{primary_dx}'. "
                    "The diagnosis is inconsistent with the billed evaluation & management service."
                )
                if CARCCode.CO_11 not in carc_codes:
                    carc_codes.append(CARCCode.CO_11)
                passed = False

        return passed

    # ── Risk Scoring ───────────────────────────────────────────────────────────

    @staticmethod
    def calculate_risk_score(
        flags: List[str],
        npi_valid: bool,
    ) -> Tuple[ClaimStatusEnum, float]:
        """
        Assign a denial-risk score and status classification based on scrubbing results.

        Scoring matrix
        --------------
        +------------------+---------------+--------------+
        | Condition        | Status        | Risk Score   |
        +==================+===============+==============+
        | 0 flags          | CLEAN         | 0.05 (5 %)   |
        +------------------+---------------+--------------+
        | 1 flag           | FLAGGED       | 0.45 (45 %)  |
        +------------------+---------------+--------------+
        | 2+ flags OR      | FATAL_ERROR   | 0.95 (95 %)  |
        | invalid NPI      |               |              |
        +------------------+---------------+--------------+

        Parameters
        ----------
        flags:
            List of flag messages accumulated during scrubbing.
        npi_valid:
            Whether the NPI passed validation. An invalid NPI always forces FATAL_ERROR.

        Returns
        -------
        Tuple[ClaimStatusEnum, float]
            Status classification and corresponding denial risk score.
        """
        flag_count = len(flags)

        if not npi_valid or flag_count >= 2:
            return ClaimStatusEnum.FATAL_ERROR, 0.95

        if flag_count == 1:
            return ClaimStatusEnum.FLAGGED, 0.45

        # 0 flags — clean claim
        return ClaimStatusEnum.CLEAN, 0.05

    # ── Orchestrator ───────────────────────────────────────────────────────────

    def scrub_claim(self, claim: ClaimInput) -> ClaimScrubResult:
        """
        Run all scrubbing checks against a single claim and return a verdict.

        Execution order
        ---------------
        1. NPI validation (structural + Luhn)
        2. Prior-authorisation check
        3. Coding consistency (ICD-10 + CPT) check
        4. Risk score calculation based on accumulated flags
        5. Assemble and return ``ClaimScrubResult``

        Parameters
        ----------
        claim:
            The inbound ``ClaimInput`` payload.

        Returns
        -------
        ClaimScrubResult
            Complete scrubbing verdict including status, risk score, flags,
            and suggested CARC codes.
        """
        flags: List[str] = []
        carc_codes: List[CARCCode] = []

        # ── Run all checks ────────────────────────────────────────────────────
        npi_valid = self.validate_npi(claim.provider_npi, flags, carc_codes)
        self.check_prior_auth(claim, flags, carc_codes)
        self.check_coding_consistency(claim, flags, carc_codes)

        # ── Calculate composite risk score ────────────────────────────────────
        status, risk_score = self.calculate_risk_score(flags, npi_valid)

        return ClaimScrubResult(
            claim_id=claim.claim_id,
            status=status,
            denial_risk_score=risk_score,
            flags=flags,
            suggested_carc_codes=carc_codes,
            billed_amount=claim.billed_amount,
        )


# ── Module-level singleton ────────────────────────────────────────────────────
# Shared across all requests; ClaimScrubber is fully stateless so this is safe.
claim_scrubber = ClaimScrubber()
