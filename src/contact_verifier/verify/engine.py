"""Turn the raw checks into a business verdict: status + confidence.

Confidence is a deliberately simple, explainable rule, not a model — a customer
asking "why is this contact 0.5?" gets a one-sentence answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from contact_verifier.db.models import EmailStatus
from contact_verifier.verify import email as email_mod
from contact_verifier.verify.dns import MxChecker


@dataclass(frozen=True)
class VerificationResult:
    normalized_email: str
    domain: str | None
    syntax_ok: bool
    domain_has_mx: bool | None
    status: EmailStatus
    confidence: float
    reason: str


class Verifier:
    def __init__(self, mx_checker: MxChecker | None = None) -> None:
        self._mx = mx_checker or MxChecker()

    def verify(self, raw_email: str) -> VerificationResult:
        parsed = email_mod.parse(raw_email)
        if not parsed.syntax_ok:
            return VerificationResult(
                normalized_email=parsed.normalized, domain=None, syntax_ok=False,
                domain_has_mx=None, status=EmailStatus.INVALID, confidence=0.0,
                reason="malformed email address",
            )

        has_mx = self._mx.has_mx(parsed.domain)
        if has_mx is True:
            status, confidence, reason = (
                EmailStatus.VALID, 0.9, "syntax ok and domain accepts mail (MX present)"
            )
        elif has_mx is False:
            status, confidence, reason = (
                EmailStatus.INVALID, 0.1, "domain cannot receive mail (no MX / NXDOMAIN)"
            )
        else:  # None: transient DNS failure, couldn't confirm
            status, confidence, reason = (
                EmailStatus.RISKY, 0.5, "syntax ok but domain deliverability unconfirmed"
            )

        return VerificationResult(
            normalized_email=parsed.normalized, domain=parsed.domain, syntax_ok=True,
            domain_has_mx=has_mx, status=status, confidence=confidence, reason=reason,
        )
