from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.api_client import ApiClient


TASK_NAME = "domatowo"
STAGING_PLAN = ((2, "E2"), (3, "B9"), (3, "I9"))
IDENTIFIER_KEYS = ("hash", "id", "identifier", "object")
POSITION_KEYS = ("position", "field", "where", "coordinates")


@dataclass(frozen=True, slots=True)
class Unit:
    identifier: str
    kind: str
    position: str


def coordinate_key(coordinate: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-K])(11|10|[1-9])", coordinate.upper())
    if not match:
        raise ValueError(f"Invalid board coordinate: {coordinate!r}")
    return ord(match.group(1)) - ord("A"), int(match.group(2)) - 1


def manhattan(first: str, second: str) -> int:
    a_col, a_row = coordinate_key(first)
    b_col, b_row = coordinate_key(second)
    return abs(a_col - b_col) + abs(a_row - b_row)


def parse_units(response: Any) -> list[Unit]:
    if not isinstance(response, Mapping) or not isinstance(response.get("objects"), list):
        raise ValueError("getObjects response contains no objects list")
    units: list[Unit] = []
    for raw in response["objects"]:
        if not isinstance(raw, Mapping):
            continue
        identifier = next((raw.get(key) for key in IDENTIFIER_KEYS if raw.get(key)), None)
        position = next((raw.get(key) for key in POSITION_KEYS if raw.get(key)), None)
        kind = raw.get("type", raw.get("typ", raw.get("kind")))
        if identifier and position and kind:
            units.append(Unit(str(identifier), str(kind).lower(), str(position).upper()))
    if len(units) != len(response["objects"]):
        raise ValueError(f"Could not parse all simulator objects: {response!r}")
    return units


def block3_coordinates(map_response: Any) -> list[str]:
    try:
        grid = map_response["map"]["grid"]
    except (KeyError, TypeError) as exc:
        raise ValueError("getMap response contains no grid") from exc
    result: list[str] = []
    for row_index, row in enumerate(grid, start=1):
        for column_index, tile in enumerate(row):
            if tile == "block3":
                result.append(f"{chr(ord('A') + column_index)}{row_index}")
    if not result:
        raise ValueError("Map contains no three-storey blocks")
    return result


def assign_nearest(scouts: Sequence[Unit], targets: Sequence[str]) -> dict[str, list[str]]:
    """Greedily balance walking by repeatedly selecting the nearest scout."""
    positions = {scout.identifier: scout.position for scout in scouts}
    routes = {scout.identifier: [] for scout in scouts}
    remaining = set(targets)
    while remaining:
        distance, identifier, target = min(
            (manhattan(position, target), identifier, target)
            for identifier, position in positions.items()
            for target in remaining
        )
        del distance
        routes[identifier].append(target)
        positions[identifier] = target
        remaining.remove(target)
    return routes


def contains_survivor(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized_key in {"found", "humanfound", "survivorfound", "partisanfound"}:
                if item is True or str(item).lower() in {"true", "yes", "found"}:
                    return True
            if contains_survivor(item):
                return True
        return False
    if isinstance(value, list):
        return any(contains_survivor(item) for item in value)
    if isinstance(value, str):
        text = value.lower()
        negatives = ("not found", "no human", "nothing found", "nie znalezion",
                     "nie odnalezion", "nie ma", "nie stwierdz", "nieobecn",
                     "nikogo", "nikt tu", "brak", "pust", "negatywne",
                     "bez kontaktu")
        positives = ("human found", "survivor found", "partisan found", "found a human",
                     "znaleziono człowie", "odnaleziono człowie",
                     "potwierdzam odnalezienie osoby", "jest tutaj osoba",
                     "partyzant odnalezion")
        if any(term in text for term in negatives):
            return False
        if any(term in text for term in positives):
            return True
        people = ("człowiek", "osoba", "mężczyzn", "partyzant", "survivor", "human")
        return any(term in text for term in people)
    return False


def survivor_field(logs: Any) -> str | None:
    entries = logs.get("logs", []) if isinstance(logs, Mapping) else []
    for entry in reversed(entries):
        if contains_survivor(entry) and isinstance(entry, Mapping) and entry.get("field"):
            return str(entry["field"])
    return None


class DomatowoWorkflow:
    """Complete economical rescue strategy for the Domatowo simulator."""

    def __init__(self, hub: ApiClient) -> None:
        self.hub = hub

    def call(self, action: str, **arguments: Any) -> Any:
        return self.hub.post_json(
            "verify",
            {"apikey": self.hub.api_key, "task": TASK_NAME,
             "answer": {"action": action, **arguments}},
            allow_http_error_response=True,
        )

    def help(self) -> Any:
        return self.call("help")

    def get_map(self) -> Any:
        return self.call("getMap")

    def call_helicopter(self, destination: str) -> Any:
        response = self.call("callHelicopter", destination=destination)
        if not isinstance(response, Mapping) or response.get("code") != 0:
            raise RuntimeError(f"Helicopter did not confirm evacuation: {response!r}")
        return response

    def resume_from_logs(self) -> Any:
        logs = self.call("getLogs")
        destination = survivor_field(logs)
        if not destination:
            raise RuntimeError("No positive survivor inspection exists in current logs")
        return {
            "destination": destination,
            "helicopter": self.call_helicopter(destination),
            "expenses": self.call("expenses"),
        }

    def run(self) -> Any:
        self.call("reset")
        targets = block3_coordinates(self.get_map())

        for passengers, _ in STAGING_PLAN:
            self.call("create", type="transporter", passengers=passengers)
        transporters = sorted(
            (unit for unit in parse_units(self.call("getObjects"))
             if "transporter" in unit.kind),
            key=lambda unit: coordinate_key(unit.position),
        )
        if len(transporters) != len(STAGING_PLAN):
            raise ValueError(f"Expected 3 transporters, got {transporters!r}")

        for transporter, (passengers, staging) in zip(transporters, STAGING_PLAN):
            self.call("move", object=transporter.identifier, where=staging)
            self.call("dismount", object=transporter.identifier, passengers=passengers)

        scouts = [
            unit for unit in parse_units(self.call("getObjects"))
            if "scout" in unit.kind
        ]
        if len(scouts) != 8:
            raise ValueError(f"Expected 8 scouts after dismount, got {scouts!r}")

        routes = assign_nearest(scouts, targets)
        inspected: list[str] = []
        for scout in scouts:
            for target in routes[scout.identifier]:
                self.call("move", object=scout.identifier, where=target)
                self.call("inspect", object=scout.identifier)
                inspected.append(target)
                logs = self.call("getLogs")
                destination = survivor_field(logs)
                if destination:
                    helicopter = self.call_helicopter(destination)
                    return {
                        "destination": destination,
                        "inspected": inspected,
                        "routes": routes,
                        "helicopter": helicopter,
                        "expenses": self.call("expenses"),
                    }
        raise RuntimeError(f"Survivor not found after inspecting all targets: {inspected}")
