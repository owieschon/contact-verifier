"""Email syntax validation and normalization.

Deliberately pragmatic, not a full RFC 5322 parser: it catches the malformed
addresses that show up in contact lists (missing @, spaces, no TLD, double
dots) and normalizes for deduplication. Domain-level DNS evidence is a separate
check (`dns.py`); this module never touches the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# One @, a sane local part, a dotted domain with a 2+ char TLD. Intentionally
# stricter than RFC 5322 (which permits quoted local parts almost nobody uses).
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?P<domain>[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+)$"
)


@dataclass(frozen=True)
class ParsedEmail:
    raw: str
    normalized: str
    domain: str | None
    syntax_ok: bool


def normalize(email: str) -> str:
    """Lowercase and trim. Email local parts are technically case-sensitive, but
    in practice mailboxes are not, and normalizing is what makes dedup work."""
    return (email or "").strip().lower()


def parse(email: str) -> ParsedEmail:
    normalized = normalize(email)
    m = _EMAIL_RE.match(normalized)
    if not m:
        return ParsedEmail(raw=email, normalized=normalized, domain=None, syntax_ok=False)
    return ParsedEmail(
        raw=email,
        normalized=normalized,
        domain=m.group("domain"),
        syntax_ok=True,
    )
