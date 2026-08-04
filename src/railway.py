from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)
FLAG_PATTERN = re.compile(r"\{FLG:[^{}]+}")


class RailwayError(RuntimeError):
    """Raised when the railway workflow cannot safely continue."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[Request, float], HttpResponse]
Sleeper = Callable[[float], None]


def urllib_transport(request: Request, timeout: float) -> HttpResponse:
    """Execute a request while preserving error bodies and response headers."""

    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, dict(response.headers), response.read())
    except HTTPError as exc:
        return HttpResponse(exc.code, dict(exc.headers), exc.read())
    except URLError as exc:
        raise RailwayError(f"Could not connect to railway API: {exc.reason}") from exc


def find_flag(value: Any) -> str | None:
    """Find a course flag anywhere in a decoded API response."""

    match = FLAG_PATTERN.search(json.dumps(value, ensure_ascii=False))
    return match.group(0) if match else None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def retry_delay(headers: Mapping[str, str], now: float) -> float | None:
    """Return the server-requested delay from common rate-limit headers."""

    retry_after = _header(headers, "Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
                return max(0.0, parsed.timestamp() - now)
            except (TypeError, ValueError, OverflowError):
                pass

    for name in ("X-RateLimit-Reset", "RateLimit-Reset"):
        raw_reset = _header(headers, name)
        if raw_reset:
            try:
                reset = float(raw_reset)
                # APIs use either an epoch timestamp or seconds until reset.
                return max(0.0, reset - now if reset > 1_000_000_000 else reset)
            except ValueError:
                pass
    return None


class RailwayClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        max_attempts: int = 12,
        transport: Transport = urllib_transport,
        sleep: Sleeper = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.transport = transport
        self.sleep = sleep
        self.clock = clock

    def call(self, answer: Mapping[str, Any]) -> Any:
        payload = json.dumps(
            {"apikey": self.api_key, "task": "railway", "answer": answer},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            self.api_url,
            data=payload,
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

        for attempt in range(1, self.max_attempts + 1):
            LOGGER.info("Railway API call action=%s attempt=%d", answer.get("action"), attempt)
            response = self.transport(request, self.timeout)
            LOGGER.info("Railway API response status=%d", response.status)
            requested_delay = retry_delay(response.headers, self.clock())

            if response.status in (429, 503):
                if attempt == self.max_attempts:
                    raise RailwayError(
                        f"Railway API still returns HTTP {response.status} after {attempt} attempts"
                    )
                delay = requested_delay
                if delay is None:
                    delay = min(60.0, 2 ** (attempt - 1)) + random.uniform(0.0, 0.25)
                LOGGER.warning("HTTP %d; retrying in %.2f seconds", response.status, delay)
                self.sleep(delay)
                continue

            try:
                decoded = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RailwayError("Railway API returned invalid UTF-8 JSON") from exc
            if not 200 <= response.status < 300:
                raise RailwayError(f"Railway API returned HTTP {response.status}: {decoded}")

            # If the last available request was consumed, wait before the next action.
            remaining = _header(response.headers, "X-RateLimit-Remaining")
            if remaining == "0" and requested_delay:
                LOGGER.info("Rate limit exhausted; waiting %.2f seconds", requested_delay)
                self.sleep(requested_delay)
            return decoded

        raise AssertionError("unreachable")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
