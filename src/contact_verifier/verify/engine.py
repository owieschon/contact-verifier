"""Turn syntax and DNS evidence into a compatibility status and rule score.

The score is an explainable rule constant, not a calibrated probability.
Neither field claims that a mailbox exists or will accept a message.
"""

from __future__ import annotations

from dataclasses import dataclass

from contact_verifier.db.models import EmailStatus
from contact_verifier.verify import email as email_mod
from contact_verifier.verify.dns import MailRoutingState, MxChecker


@dataclass(frozen=True)
class VerificationResult:
    normalized_email: str
    domain: str | None
    syntax_ok: bool
    mail_routing_state: MailRoutingState | None
    status: EmailStatus
    heuristic_score: float
    reason: str


class Verifier:
    def __init__(self, mx_checker: MxChecker | None = None) -> None:
        self._mx = mx_checker or MxChecker()

    def verify(self, raw_email: str) -> VerificationResult:
        parsed = email_mod.parse(raw_email)
        if not parsed.syntax_ok:
            return VerificationResult(
                normalized_email=parsed.normalized, domain=None, syntax_ok=False,
                mail_routing_state=None, status=EmailStatus.INVALID, heuristic_score=0.0,
                reason="malformed email address",
            )

        routing = self._mx.routing_state(parsed.domain)
        if routing in {MailRoutingState.MX, MailRoutingState.IMPLICIT_MX}:
            status, score, reason = (
                EmailStatus.VALID,
                0.9,
                f"syntax passed and usable DNS mail route found ({routing.value})",
            )
        elif routing in {
            MailRoutingState.NULL_MX,
            MailRoutingState.NXDOMAIN,
            MailRoutingState.NO_ADDRESS,
        }:
            status, score, reason = (
                EmailStatus.INVALID, 0.1, f"domain has no usable DNS mail route ({routing.value})"
            )
        else:
            status, score, reason = (
                EmailStatus.RISKY, 0.5, "syntax passed but DNS routing evidence stayed transient"
            )

        return VerificationResult(
            normalized_email=parsed.normalized, domain=parsed.domain, syntax_ok=True,
            mail_routing_state=routing, status=status, heuristic_score=score, reason=reason,
        )
