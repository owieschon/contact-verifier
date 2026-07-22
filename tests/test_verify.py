"""Unit tests for the verification engine — no network, no real waiting.

The DNS resolver and the sleep function are injected, so these exercise the
retry/backoff/cache/rate-limit logic deterministically.
"""

import dns.exception
import dns.resolver
import pytest

from contact_verifier.db.models import EmailStatus
from contact_verifier.verify.dns import MailRoutingState, MxChecker
from contact_verifier.verify.email import parse
from contact_verifier.verify.engine import Verifier

# --- syntax ----------------------------------------------------------------

@pytest.mark.parametrize("good", [
    "jane.doe@example.com", "a+tag@sub.example.co.uk", "USER@Example.COM",
])
def test_valid_syntax(good):
    p = parse(good)
    assert p.syntax_ok and p.domain and p.normalized == good.strip().lower()


@pytest.mark.parametrize("bad", [
    "no-at-sign.com", "two@@example.com", "spaces in@example.com",
    "missing-tld@example", "@example.com", "trailing@example.com.",
])
def test_invalid_syntax(bad):
    assert not parse(bad).syntax_ok


# --- MX checker: retries, backoff, cache -----------------------------------

def _checker(resolve_fn, **kw):
    sleeps: list[float] = []
    kw.setdefault("rate_limit_per_s", 0)  # disable rate limit unless a test wants it
    return MxChecker(resolve_fn=resolve_fn, sleep=sleeps.append, **kw), sleeps


def test_mx_present_is_explicit_route():
    checker, _ = _checker(lambda _d, _t: ["mx1.example.com"])
    assert checker.routing_state("example.com") is MailRoutingState.MX


class _NullMx:
    exchange = "."


def test_null_mx_is_definitive_refusal():
    checker, _ = _checker(lambda _d, _t: [_NullMx()])
    assert checker.routing_state("example.com") is MailRoutingState.NULL_MX


@pytest.mark.parametrize("address_type", ["A", "AAAA"])
def test_no_mx_with_address_uses_implicit_mx(address_type):
    def resolve(_domain, rdtype):
        if rdtype == "MX":
            raise dns.resolver.NoAnswer()
        if rdtype == address_type:
            return ["address"]
        raise dns.resolver.NoAnswer()

    checker, _ = _checker(resolve)
    assert checker.routing_state("example.com") is MailRoutingState.IMPLICIT_MX


def test_no_mx_and_no_address_is_definitive():
    def resolve(_domain, _rdtype):
        raise dns.resolver.NoAnswer()

    checker, _ = _checker(resolve)
    assert checker.routing_state("example.com") is MailRoutingState.NO_ADDRESS


def test_temporary_failure_during_implicit_mx_lookup_retries():
    calls = {"n": 0}

    def resolve(_domain, rdtype):
        if rdtype == "MX":
            raise dns.resolver.NoAnswer()
        calls["n"] += 1
        raise dns.resolver.NoNameservers()

    checker, sleeps = _checker(resolve, max_retries=1)
    assert checker.routing_state("example.com") is MailRoutingState.TRANSIENT
    assert calls["n"] == 2
    assert len(sleeps) == 1


def test_nxdomain_is_false_and_not_retried():
    calls = {"n": 0}

    def resolve(_d, _rdtype):
        calls["n"] += 1
        raise dns.resolver.NXDOMAIN()

    checker, _ = _checker(resolve, max_retries=3)
    assert checker.routing_state("nope.invalid") is MailRoutingState.NXDOMAIN
    assert calls["n"] == 1, "NXDOMAIN is definitive — must not retry"


def test_transient_failure_retries_then_returns_unknown():
    calls = {"n": 0}

    def resolve(_d, _rdtype):
        calls["n"] += 1
        raise dns.exception.Timeout()

    checker, sleeps = _checker(resolve, max_retries=3, backoff_base_s=0.1)
    assert checker.routing_state("slow.example.com") is MailRoutingState.TRANSIENT
    assert calls["n"] == 4, "1 initial + 3 retries"
    assert len(sleeps) == 3, "backoff between the 3 retries"
    assert sleeps == sorted(sleeps), "exponential backoff is non-decreasing"


def test_transient_then_success():
    calls = {"n": 0}

    def resolve(_d, _rdtype):
        calls["n"] += 1
        if calls["n"] == 1:
            raise dns.exception.Timeout()
        return ["mx1"]

    checker, _ = _checker(resolve, max_retries=3, rate_limit_per_s=20)
    assert checker.routing_state("example.com") is MailRoutingState.MX
    assert calls["n"] == 2


def test_decided_answers_are_cached():
    calls = {"n": 0}

    def resolve(_d, _rdtype):
        calls["n"] += 1
        return ["mx1"]

    checker, _ = _checker(resolve)
    assert checker.routing_state("example.com") is MailRoutingState.MX
    assert checker.routing_state("example.com") is MailRoutingState.MX
    assert calls["n"] == 1, "second lookup served from cache"


def test_cache_is_bounded_lru():
    """The cache must not grow without limit; least-recently-used entries are
    evicted past cache_maxsize."""
    calls = {"n": 0}

    def resolve(_d, _rdtype):
        calls["n"] += 1
        return ["mx"]

    checker = MxChecker(resolve_fn=resolve, rate_limit_per_s=0, cache_maxsize=2)
    checker.routing_state("a.com")
    checker.routing_state("b.com")
    checker.routing_state("a.com")
    checker.routing_state("c.com")
    assert calls["n"] == 3
    checker.routing_state("a.com")
    checker.routing_state("b.com")
    assert calls["n"] == 4


def test_rate_limit_waits_between_calls():
    sleeps: list[float] = []
    checker = MxChecker(
        resolve_fn=lambda _d, _t: ["mx"], rate_limit_per_s=10,
        sleep=sleeps.append, clock=lambda: 0.0,   # clock frozen -> interval never elapses
    )
    checker.routing_state("a.com")
    checker.routing_state("b.com")
    assert any(w > 0 for w in sleeps), "rate limiter should pace successive calls"


# --- engine: routing state -> status/heuristic score -----------------------

def test_engine_maps_outcomes():
    valid = Verifier(MxChecker(resolve_fn=lambda _d, _t: ["mx"])).verify("ok@example.com")
    assert valid.status is EmailStatus.VALID and valid.heuristic_score == 0.9
    assert valid.reason == "syntax passed and usable DNS mail route found (mx)"

    def nx(_d, _rdtype):
        raise dns.resolver.NXDOMAIN()

    invalid = Verifier(MxChecker(resolve_fn=nx)).verify("ok@nope.invalid")
    assert invalid.status is EmailStatus.INVALID
    assert invalid.reason == "domain has no usable DNS mail route (nxdomain)"

    bad_syntax = Verifier(MxChecker(resolve_fn=lambda _d, _t: ["mx"])).verify("nope")
    assert bad_syntax.status is EmailStatus.INVALID and bad_syntax.heuristic_score == 0.0

    def timeout(_d, _rdtype):
        raise dns.exception.Timeout()

    risky = Verifier(MxChecker(resolve_fn=timeout, max_retries=0)).verify("ok@slow.com")
    assert risky.status is EmailStatus.RISKY and risky.heuristic_score == 0.5
    assert risky.reason == "syntax passed but DNS routing evidence stayed transient"
