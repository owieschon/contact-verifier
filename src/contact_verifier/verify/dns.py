"""Domain deliverability via DNS MX lookup — the service's external dependency.

This is where the integration craft lives. A network call to a flaky external
system gets:
  - a per-attempt timeout, so one slow resolver can't hang a request;
  - bounded retries with exponential backoff + jitter on *transient* failures
    (timeout, SERVFAIL) but not on definitive ones (NXDOMAIN means the domain
    does not exist — retrying is pointless);
  - a client-side rate limit, so a bulk verify run doesn't hammer the resolver;
  - a short-lived, size-bounded (LRU) cache, because the same domains recur
    constantly in a contact list and their MX records don't change between
    requests — bounded so a long-lived process can't grow it without limit.

The resolver and the clock/sleep are injected so the whole thing is unit-testable
with no network and no real waiting.
"""

from __future__ import annotations

import random
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import dns.exception
import dns.resolver

from contact_verifier.logging import get_logger

log = get_logger()

class MailRoutingState(StrEnum):
    MX = "mx"
    IMPLICIT_MX = "implicit_mx"
    NULL_MX = "null_mx"
    NXDOMAIN = "nxdomain"
    NO_ADDRESS = "no_address"
    TRANSIENT = "transient"


def _default_resolver(timeout_s: float) -> Callable[[str, str], object]:
    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout_s
    resolver.lifetime = timeout_s

    def resolve(domain: str, rdtype: str) -> object:
        return resolver.resolve(domain, rdtype)

    return resolve


@dataclass
class _CacheEntry:
    value: MailRoutingState
    expires_at: float


class MxChecker:
    def __init__(
        self,
        *,
        timeout_s: float = 3.0,
        max_retries: int = 3,
        rate_limit_per_s: float = 20.0,
        backoff_base_s: float = 0.1,
        cache_ttl_s: int = 3600,
        cache_maxsize: int = 10_000,
        resolve_fn: Callable[[str, str], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._resolve = resolve_fn or _default_resolver(timeout_s)
        self._max_retries = max_retries
        self._min_interval = 1.0 / rate_limit_per_s if rate_limit_per_s > 0 else 0.0
        self._backoff_base = backoff_base_s
        self._cache_ttl = cache_ttl_s
        self._cache_maxsize = cache_maxsize
        self._clock = clock
        self._sleep = sleep
        # Bounded LRU: a long-lived process verifying many domains can't grow the
        # cache without limit. OrderedDict gives O(1) move-to-end / evict-oldest.
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._last_call_at = 0.0

    def routing_state(self, domain: str) -> MailRoutingState:
        cached = self._cache.get(domain)
        if cached is not None and cached.expires_at > self._clock():
            self._cache.move_to_end(domain)  # mark recently used
            return cached.value

        result = self._lookup_with_retries(domain)
        # Transient failures are not cached so a later request can retry.
        if result is not MailRoutingState.TRANSIENT:
            self._cache[domain] = _CacheEntry(
                value=result, expires_at=self._clock() + self._cache_ttl
            )
            self._cache.move_to_end(domain)
            if len(self._cache) > self._cache_maxsize:
                self._cache.popitem(last=False)  # evict least-recently-used
        return result

    def _lookup_with_retries(self, domain: str) -> MailRoutingState:
        for attempt in range(self._max_retries + 1):
            self._respect_rate_limit()
            try:
                return self._lookup_once(domain)
            except dns.resolver.NXDOMAIN:
                return MailRoutingState.NXDOMAIN
            except (dns.exception.Timeout, dns.resolver.NoNameservers) as exc:
                if attempt >= self._max_retries:
                    log.warning("mx_lookup_exhausted", domain=domain, error=str(exc))
                    return MailRoutingState.TRANSIENT
                backoff = (2 ** attempt) * self._backoff_base + random.uniform(0, 0.05)
                self._sleep(backoff)
        return MailRoutingState.TRANSIENT

    def _lookup_once(self, domain: str) -> MailRoutingState:
        try:
            answers = list(self._resolve(domain, "MX"))
        except dns.resolver.NoAnswer:
            return self._implicit_mx_state(domain)
        if any(
            str(getattr(answer, "exchange", "")).strip() == "."
            for answer in answers
        ):
            return MailRoutingState.NULL_MX
        if answers:
            return MailRoutingState.MX
        return self._implicit_mx_state(domain)

    def _implicit_mx_state(self, domain: str) -> MailRoutingState:
        for rdtype in ("A", "AAAA"):
            try:
                if list(self._resolve(domain, rdtype)):
                    return MailRoutingState.IMPLICIT_MX
            except dns.resolver.NoAnswer:
                continue
        return MailRoutingState.NO_ADDRESS

    def _respect_rate_limit(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (self._clock() - self._last_call_at)
        if wait > 0:
            self._sleep(wait)
        self._last_call_at = self._clock()
