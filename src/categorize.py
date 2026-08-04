from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from src.api_client import ApiClient, ApiClientError


TASK_NAME = "categorize"
EXPECTED_ITEMS = 10
FLAG_PATTERN = re.compile(r"\{FLG:[^}]+}")
ID_FIELDS = ("code", "id", "identifier", "item_id")
DESCRIPTION_FIELDS = ("description", "desc", "content", "text", "item")

PROMPTS = (
    (
        "Reactor=NEU always. DNG=weapon/mine/firearm/explosive. "
        "NEU=safe/tool/part.\n"
        "{id}: {description}\n"
        "Classification (DNG/NEU):"
    ),
    (
        "DNG=gun/mine/weapon/explosive. NEU=part/tool/reactor.\n"
        "{id}: {description}\n"
        "Label:"
    ),
    (
        "DNG=weapon/explosive/firearm/mine. NEU=safe/reactor.\n"
        "Item {id}: {description}\n"
        "This item is classified as "
    ),
    (
        "Classify as DNG(weapon/mine/firearm) or NEU(safe/reactor). "
        "Reactor=NEU.\n"
        "{id}: {description}\n"
        "Answer:"
    ),
)


@dataclass(frozen=True, slots=True)
class CargoItem:
    identifier: str
    description: str


class AttemptResult(Enum):
    SUCCESS = "success"
    RETRY = "retry"
    COMPLETE = "complete"


def parse_items(payload: bytes) -> list[CargoItem]:
    """Parse and validate the Hub's UTF-8 CSV payload."""

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Cargo CSV is not valid UTF-8") from exc

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if reader.fieldnames is None:
        raise ValueError("Cargo CSV has no header")
    fields = {name.strip().lower(): name for name in reader.fieldnames if name}
    id_field = next((fields[name] for name in ID_FIELDS if name in fields), None)
    description_field = next(
        (fields[name] for name in DESCRIPTION_FIELDS if name in fields), None
    )
    if (id_field is None or description_field is None) and len(reader.fieldnames) == 2:
        id_field, description_field = reader.fieldnames
    if id_field is None or description_field is None:
        available = ", ".join(fields) or "none"
        raise ValueError(
            f"Unsupported cargo CSV columns ({available}); expected code and description"
        )

    items: list[CargoItem] = []
    for row_number, row in enumerate(reader, start=2):
        identifier = (row.get(id_field) or "").strip()
        description = (row.get(description_field) or "").strip()
        if not identifier or not description:
            raise ValueError(f"Cargo CSV row {row_number} has an empty field")
        items.append(CargoItem(identifier, description))

    if len(items) != EXPECTED_ITEMS:
        raise ValueError(f"Expected {EXPECTED_ITEMS} cargo items, got {len(items)}")
    if len({item.identifier for item in items}) != len(items):
        raise ValueError("Cargo CSV contains duplicate ids")
    return items


def build_prompt(item: CargoItem, template: str = PROMPTS[0]) -> str:
    return template.replace("{id}", item.identifier).replace(
        "{description}", item.description
    )


def find_flag(response: Any) -> str | None:
    match = FLAG_PATTERN.search(str(response))
    return match.group(0) if match else None


def reset(client: ApiClient) -> Mapping[str, Any]:
    response = _submit_prompt(client, "reset")
    print(f"RESET -> balance={response.get('balance', '?')}")
    return response


def fetch_items(client: ApiClient) -> list[CargoItem]:
    return parse_items(client.request_bytes(f"data/{client.api_key}/categorize.csv"))


def classify(
    client: ApiClient, item: CargoItem, prompt_template: str
) -> Mapping[str, Any]:
    return _submit_prompt(client, build_prompt(item, prompt_template))


def _submit_prompt(client: ApiClient, prompt: str) -> Mapping[str, Any]:
    response = client.post_json(
        "verify",
        {
            "apikey": client.api_key,
            "task": TASK_NAME,
            "answer": {"prompt": prompt},
        },
        allow_http_error_response=True,
    )
    if not isinstance(response, Mapping):
        raise ApiClientError("Hub verification response is not a JSON object")
    return response


def try_prompt(
    client: ApiClient, prompt_template: str
) -> tuple[AttemptResult, str | None]:
    reset(client)
    items = fetch_items(client)
    print(f"\n--- Prompt:\n{prompt_template}\n")

    for item in items:
        response = classify(client, item, prompt_template)
        debug_value = response.get("debug", {})
        debug = debug_value if isinstance(debug_value, Mapping) else {}
        code = response.get("code")
        balance = response.get("balance") or debug.get("balance", "?")
        classified = debug.get("classified_items", "?")
        output = str(debug.get("output", ""))
        print(
            f"  {item.identifier} [{code}] classified={classified} "
            f"bal={balance} -> {output[:60]!r}"
        )

        if flag := find_flag(response):
            print(f"\n*** FLAG: {flag} ***")
            return AttemptResult.SUCCESS, flag
        if code == -910:
            print("  Budget exhausted")
            return AttemptResult.RETRY, None
        if code == -890:
            print(f"  Wrong format! Model said: {output[:100]}")
            return AttemptResult.RETRY, None

    print("\nAll items attempted. Check classified count.")
    return AttemptResult.COMPLETE, None


def run_classification(client: ApiClient) -> str | None:
    for version, prompt_template in enumerate(PROMPTS, start=1):
        print(f"\n{'=' * 50}\nTrying prompt v{version}")
        result, flag = try_prompt(client, prompt_template)
        if result is AttemptResult.SUCCESS:
            print("SUCCESS!")
            return flag
        if result is AttemptResult.RETRY:
            print(f"v{version} failed, trying next...")
            continue
        print(f"v{version} completed, check results")
        return None

    raise ApiClientError("All prompt variants failed")
