from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.api_client import ApiClient


TOKEN_LIMIT = 1500
MAX_ITERATIONS = 8
LINE_RE = re.compile(
    r"^\s*\[?(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<time>\d{1,2}:\d{2})(?::\d{2})?\]?"
    r"\s+\[?(?P<level>TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERR(?:OR)?|CRIT(?:ICAL)?|ALERT|EMERG)\]?"
    r"\s+(?P<body>.+?)\s*$",
    re.IGNORECASE,
)
COMPONENT_RE = re.compile(r"\b(?=[A-Z0-9_-]*\d)[A-Z][A-Z0-9_-]{2,}\b")
FEEDBACK_ID_RE = re.compile(r"\b(?=[A-Z0-9_-]*\d)[A-Z][A-Z0-9_-]{2,}\b")
LEVEL_SCORE = {
    "TRACE": 0, "DEBUG": 0, "INFO": 1, "NOTICE": 2, "WARN": 5,
    "WARNING": 5, "ERR": 8, "ERROR": 8, "CRIT": 12, "CRITICAL": 12,
    "ALERT": 13, "EMERG": 14,
}
PLANT_TERMS = (
    "power", "voltage", "current", "frequency", "generator", "turbine",
    "transformer", "breaker", "grid", "battery", "ups", "cool", "coolant",
    "temperature", "thermal", "heat", "pump", "water", "tank", "valve",
    "pressure", "flow", "reactor", "control rod", "steam", "condenser",
    "sensor", "controller", "plc", "software", "firmware", "system", "kernel",
    "network", "bus", "interlock", "trip", "shutdown", "alarm", "failure",
    "fault", "offline", "runaway", "leak", "emergency", "eccs",
)
FILLER_RE = re.compile(
    r"\b(?:the|a|an|has|had|have|was|were|is|been|being|detected|reported|"
    r"observed|currently|approximately|system|unit)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class LogEvent:
    date: str
    time: str
    level: str
    component: str
    message: str
    source_index: int

    @property
    def search_text(self) -> str:
        return f"{self.component} {self.message}".upper()

    def compact(self) -> str:
        message = FILLER_RE.sub("", self.message)
        message = re.sub(r"\s+", " ", message).strip(" .;:-")
        return f"[{self.date} {self.time}] [{normalize_level(self.level)}] {self.component} {message}".strip()


def normalize_level(level: str) -> str:
    return {"WARNING": "WARN", "ERR": "ERROR", "CRITICAL": "CRIT"}.get(level.upper(), level.upper())


def parse_events(text: str) -> list[LogEvent]:
    events: list[LogEvent] = []
    for index, line in enumerate(text.splitlines()):
        match = LINE_RE.match(line)
        if not match:
            continue
        body = match.group("body")
        bracketed = re.match(r"^\[([^\]]+)\]\s*(.*)$", body)
        if bracketed:
            component, message = bracketed.group(1).strip(), bracketed.group(2).strip()
        else:
            identifiers = COMPONENT_RE.findall(body)
            component = identifiers[0] if identifiers else "PLANT"
            message = body
            if identifiers and message.startswith(component):
                message = message[len(component):].lstrip(" :-")
        events.append(LogEvent(match.group("date"), match.group("time"), match.group("level"), component, message, index))
    return events


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate for English logs."""
    return math.ceil(len(text.encode("utf-8")) / 3)


def _score(event: LogEvent, forced_terms: set[str]) -> int:
    text = event.search_text
    score = LEVEL_SCORE.get(event.level.upper(), 0)
    score += 4 * sum(term in text for term in PLANT_TERMS)
    score += 30 * sum(term in text for term in forced_terms)
    return score


def build_condensed_log(
    events: Sequence[LogEvent],
    *,
    forced_terms: Iterable[str] = (),
    token_limit: int = TOKEN_LIMIT,
) -> str:
    forced = {term.upper() for term in forced_terms if term.strip()}
    candidates = [event for event in events if _score(event, forced) >= 5]
    ranked = sorted(candidates, key=lambda event: (-_score(event, forced), event.source_index))

    selected: list[LogEvent] = []
    represented: set[str] = set()
    # First retain the strongest event for each affected component.
    for event in ranked:
        key = event.component.upper()
        if key not in represented:
            selected.append(event)
            represented.add(key)
    for event in ranked:
        if event not in selected:
            selected.append(event)

    accepted: list[LogEvent] = []
    for event in selected:
        trial = "\n".join(item.compact() for item in accepted + [event])
        if estimate_tokens(trial) <= token_limit:
            accepted.append(event)
    return "\n".join(event.compact() for event in sorted(accepted, key=lambda item: item.source_index))


def feedback_terms(response: Any, known_components: Iterable[str]) -> set[str]:
    text = str(response).upper()
    known = {component.upper() for component in known_components}
    terms = {item for item in FEEDBACK_ID_RE.findall(text) if item in known}
    terms.update(
        term.upper()
        for term in PLANT_TERMS
        if re.search(rf"(?<![A-Z0-9]){re.escape(term.upper())}(?![A-Z0-9])", text)
    )
    return terms


class FailureClient:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def fetch_log(self) -> str:
        payload = self.client.request_bytes(f"data/{self.client.api_key}/failure.log")
        return payload.decode("utf-8", errors="replace")

    def verify(self, logs: str) -> Any:
        if estimate_tokens(logs) > TOKEN_LIMIT:
            raise ValueError(f"Condensed logs exceed the {TOKEN_LIMIT}-token budget")
        return self.client.post_json(
            "verify",
            {"apikey": self.client.api_key, "task": "failure", "answer": {"logs": logs}},
            allow_http_error_response=True,
        )

    def solve(self) -> tuple[dict[str, int], str, Any]:
        raw = self.fetch_log()
        events = parse_events(raw)
        if not events:
            raise ValueError("Downloaded failure.log contains no recognized log events")
        stats = {"bytes": len(raw.encode("utf-8")), "lines": len(raw.splitlines()), "estimated_tokens": estimate_tokens(raw)}
        forced: set[str] = set()
        previous_logs = ""
        response: Any = None
        components = {event.component for event in events}
        for _ in range(MAX_ITERATIONS):
            logs = build_condensed_log(events, forced_terms=forced)
            if not logs or logs == previous_logs:
                break
            previous_logs = logs
            response = self.verify(logs)
            if "{FLG:" in str(response):
                return stats, logs, response
            additions = feedback_terms(response, components) - forced
            if not additions:
                break
            forced.update(additions)
        return stats, previous_logs, response
