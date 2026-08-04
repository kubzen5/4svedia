from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from src.api_client import ApiClient, ApiConfig
from src.findhim import (
    PersonLocation,
    build_answer,
    find_nearby_match,
    parse_person_location,
    parse_power_plants,
)


CANDIDATES_PATH = Path("data/S01E01/transport_people.csv")
LOOKUP_ENDPOINT = "api/people/locations"
MAX_DISTANCE_KM = 10.0


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing {name}. Configure it as documented in .env-example "
            "and expose it to the process environment."
        )
    return value


def read_candidates(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(
            f"Missing {path}. Run `uv run s01e01.py` first to refresh candidates."
        )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(not row.get("name") or not row.get("surname") for row in rows):
        raise RuntimeError(f"{path} does not contain valid name and surname columns")
    return rows


def lookup_person(
    client: ApiClient,
    endpoint: str,
    candidate: dict[str, str],
) -> PersonLocation:
    payload: dict[str, Any] = {
        "apikey": client.api_key,
        "name": candidate["name"],
        "surname": candidate["surname"],
    }
    response = client.post_json(endpoint, payload)
    return parse_person_location(
        response,
        name=candidate["name"],
        surname=candidate["surname"],
    )


def main() -> None:
    client = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
        )
    )
    endpoint = os.getenv("FINDHIM_LOOKUP_ENDPOINT", LOOKUP_ENDPOINT).strip()
    maximum_distance = float(os.getenv("FINDHIM_MAX_DISTANCE_KM", MAX_DISTANCE_KM))

    plants = parse_power_plants(
        client.get_json(f"data/{client.api_key}/findhim_locations.json")
    )
    people = [
        lookup_person(client, endpoint, candidate)
        for candidate in read_candidates(CANDIDATES_PATH)
    ]
    match = find_nearby_match(
        people,
        plants,
        maximum_distance_km=maximum_distance,
    )
    verification = client.post_json(
        "verify",
        {
            "apikey": client.api_key,
            "task": "findhim",
            "answer": build_answer(match),
        },
    )
    print(verification)


if __name__ == "__main__":
    main()
