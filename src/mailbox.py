from __future__ import annotations

import re
import time
from dataclasses import dataclass
from itertools import product
from typing import Any, Iterable, Mapping, Sequence

from src.api_client import ApiClient, ApiClientError


TASK_NAME = "mailbox"
MAX_PAGES = 20
MAX_POLL_ATTEMPTS = 6
SEARCH_QUERIES = (
    "from:proton.me",
    "hasło OR password OR credentials",
    "SEC- OR ticket OR zgłoszenie",
)
FLAG_RE = re.compile(r"\{FLG:[^{}]+}")
PLANT_RE = re.compile(r"\bPWR\d+PL\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
CODE_RE = re.compile(r"\bSEC-[A-Za-z0-9]{32}\b")
PASSWORD_PATTERNS = (
    re.compile(r"(?:has(?:ł|l)o|password)[^\n:]{0,80}(?:\s*:\s*|\n+)\s*([^\s]+)", re.IGNORECASE),
    re.compile(r"logować\s+się\s+hasłem\s*:\s*([^\s]+)", re.IGNORECASE),
)
ATTACK_TERMS = ("bomb", "atak", "zbombard", "zaatak")
CORRECTION_TERMS = ("poprawny", "właściwy", "korekt", "correct")


@dataclass(frozen=True, slots=True)
class MailFacts:
    passwords: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    confirmation_codes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return bool(self.passwords and self.dates and self.confirmation_codes)


def _items(response: Any, action: str) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        raise ApiClientError(f"zmail {action} returned an unsuccessful response")
    value = response.get("items", [])
    if not isinstance(value, list):
        raise ApiClientError(f"zmail {action} response has no items list")
    return [item for item in value if isinstance(item, Mapping)]


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def extract_facts(messages: Sequence[Mapping[str, Any]]) -> MailFacts:
    password_candidates: list[tuple[int, str]] = []
    date_candidates: list[tuple[int, str]] = []
    code_candidates: list[tuple[int, str]] = []

    for message in messages:
        body = str(message.get("message", ""))
        subject = str(message.get("subject", ""))
        text = f"{subject}\n{body}"
        lowered = text.casefold()

        for pattern in PASSWORD_PATTERNS:
            for match in pattern.finditer(body):
                candidate = match.group(1).strip(".,;:!?()[]{}\"'")
                if 4 <= len(candidate) <= 128:
                    password_candidates.append((10, candidate))

        if any(term in lowered for term in ATTACK_TERMS):
            for candidate in DATE_RE.findall(body):
                date_candidates.append((10, candidate))

        correction_score = 20 if any(term in lowered for term in CORRECTION_TERMS) else 10
        for candidate in CODE_RE.findall(body):
            code_candidates.append((correction_score, candidate))

    ordered = lambda pairs: _unique(value for _, value in sorted(pairs, key=lambda item: -item[0]))
    return MailFacts(ordered(password_candidates), ordered(date_candidates), ordered(code_candidates))


class ZmailClient:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def call(self, action: str, **parameters: Any) -> Mapping[str, Any]:
        response = self.client.post_json(
            "api/zmail",
            {"apikey": self.client.api_key, "action": action, **parameters},
            allow_http_error_response=True,
        )
        if not isinstance(response, Mapping):
            raise ApiClientError(f"zmail {action} response is not a JSON object")
        return response

    def help(self) -> Mapping[str, Any]:
        return self.call("help", page=1)

    def search(self, query: str) -> list[Mapping[str, Any]]:
        found: list[Mapping[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            response = self.call("search", query=query, page=page, perPage=20)
            found.extend(_items(response, "search"))
            pagination = response.get("pagination", {})
            total_pages = pagination.get("totalPages", 1) if isinstance(pagination, Mapping) else 1
            if page >= int(total_pages):
                return found
        raise ApiClientError(f"zmail search exceeded {MAX_PAGES} pages")

    def get_thread(self, thread_id: int) -> list[Mapping[str, Any]]:
        return _items(self.call("getThread", threadID=thread_id), "getThread")

    def get_messages(self, ids: Sequence[str | int]) -> list[Mapping[str, Any]]:
        if not ids:
            return []
        return _items(self.call("getMessages", ids=list(ids)), "getMessages")

    def read_search_results(self, results: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """Refresh threads first because row/message IDs can change in an active inbox."""
        thread_ids = _unique(str(item.get("threadID", "")) for item in results)
        ids: list[str | int] = []
        for thread_id in thread_ids:
            if not thread_id.isdigit():
                continue
            for item in self.get_thread(int(thread_id)):
                identifier = item.get("messageID") or item.get("rowID")
                if isinstance(identifier, (str, int)):
                    ids.append(identifier)
        return self.get_messages(list(dict.fromkeys(ids)))

    def verify(self, answer: Mapping[str, str]) -> Mapping[str, Any]:
        response = self.client.post_json(
            "verify",
            {"apikey": self.client.api_key, "task": TASK_NAME, "answer": dict(answer)},
            allow_http_error_response=True,
        )
        if not isinstance(response, Mapping):
            raise ApiClientError("mailbox verification response is not a JSON object")
        return response

    def collect(self) -> MailFacts:
        proton_results = self.search(SEARCH_QUERIES[0])
        proton_messages = self.read_search_results(proton_results)
        plant_ids = _unique(
            match.group(0).upper()
            for message in proton_messages
            for match in PLANT_RE.finditer(str(message.get("message", "")))
        )

        results = list(proton_results)
        for query in (*SEARCH_QUERIES[1:], *plant_ids):
            results.extend(self.search(query))
        messages = self.read_search_results(results)
        return extract_facts(messages)

    def solve(self, *, sleep_seconds: float = 2.0) -> Mapping[str, Any]:
        help_response = self.help()
        actions = help_response.get("actions")
        required_actions = {"search", "getThread", "getMessages"}
        if not isinstance(actions, Mapping) or not required_actions <= set(actions):
            raise ApiClientError("zmail help does not advertise the required actions")

        last_response: Mapping[str, Any] | None = None
        attempted: set[tuple[str, str, str]] = set()
        for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
            facts = self.collect()
            if facts.complete:
                combinations = product(facts.passwords, facts.dates, facts.confirmation_codes)
                for password, date, confirmation_code in combinations:
                    key = (password, date, confirmation_code)
                    if key in attempted:
                        continue
                    attempted.add(key)
                    last_response = self.verify(
                        {"password": password, "date": date, "confirmation_code": confirmation_code}
                    )
                    if FLAG_RE.search(str(last_response)):
                        return last_response
            if attempt < MAX_POLL_ATTEMPTS:
                time.sleep(sleep_seconds)

        if last_response is not None:
            return last_response
        raise ApiClientError("mailbox facts remained incomplete after repeated searches")
