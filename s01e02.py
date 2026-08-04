from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiConfig
from src.findhim import (
    PersonLocation,
    build_answer,
    find_nearby_match,
    parse_access_level,
    parse_person_locations,
    parse_power_plants,
)


CANDIDATES_PATH = Path("data/S01E01/transport_people.csv")
LOCATION_ENDPOINT = "api/location"
ACCESS_LEVEL_ENDPOINT = "api/accesslevel"
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
) -> list[PersonLocation]:
    payload: dict[str, Any] = {
        "apikey": client.api_key,
        "name": candidate["name"],
        "surname": candidate["surname"],
    }
    response = client.post_json(endpoint, payload)
    return parse_person_locations(
        response,
        name=candidate["name"],
        surname=candidate["surname"],
    )


def lookup_access_level(client: ApiClient, candidate: dict[str, str]) -> int | str:
    birth_date = candidate.get("birthDate", "")
    try:
        birth_year = int(birth_date[:4])
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid birthDate for {candidate['name']} {candidate['surname']}: {birth_date!r}"
        ) from exc
    response = client.post_json(
        ACCESS_LEVEL_ENDPOINT,
        {
            "apikey": client.api_key,
            "name": candidate["name"],
            "surname": candidate["surname"],
            "birthYear": birth_year,
        },
    )
    return parse_access_level(response)


def main() -> None:
    load_dotenv(override=True)

    client = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
        )
    )
    maximum_distance = float(os.getenv("FINDHIM_MAX_DISTANCE_KM", MAX_DISTANCE_KM))

    plants = parse_power_plants(
        client.get_json(f"data/{client.api_key}/findhim_locations.json")
    )
    candidates = read_candidates(CANDIDATES_PATH)
    people = [
        location
        for candidate in candidates
        for location in lookup_person(client, LOCATION_ENDPOINT, candidate)
    ]
    match = find_nearby_match(
        people,
        plants,
        maximum_distance_km=maximum_distance,
    )
    matched_candidate = next(
        candidate
        for candidate in candidates
        if candidate["name"] == match.person.name
        and candidate["surname"] == match.person.surname
    )
    access_level = lookup_access_level(client, matched_candidate)
    match = type(match)(
        person=PersonLocation(
            match.person.name,
            match.person.surname,
            access_level,
            match.person.coordinates,
        ),
        power_plant=match.power_plant,
        distance_km=match.distance_km,
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
