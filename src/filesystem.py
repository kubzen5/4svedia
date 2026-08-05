from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from src.api_client import ApiClient, ApiClientError


TASK_NAME = "filesystem"
NOTES_ENDPOINT = "dane/natan_notes.zip"


class FilesystemError(ValueError):
    """Raised when Natan's notes are incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class TradeData:
    needs: Mapping[str, Mapping[str, int]]
    managers: Mapping[str, str]
    sales: Mapping[str, Sequence[str]]


def ascii_name(value: str) -> str:
    polish = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    normalized = unicodedata.normalize("NFKD", value.translate(polish))
    return "".join(character for character in normalized if not unicodedata.combining(character))


def read_notes(payload: bytes) -> dict[str, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return {
                PurePosixPath(name).name: archive.read(name).decode("utf-8-sig")
                for name in archive.namelist()
                if not name.endswith("/")
            }
    except (zipfile.BadZipFile, UnicodeDecodeError, KeyError) as exc:
        raise FilesystemError("Natan notes are not a valid UTF-8 ZIP archive") from exc


def parse_needs(text: str) -> dict[str, dict[str, int]]:
    city_patterns = {
        "Opalino": r"Opalino.*?(\d+) chlebow, (\d+) butelek wody i (\d+) mlotkow",
        "Domatowo": r"Domatowa.*?(\d+) makaronu, (\d+) butelek wody i (\d+) lopat",
        "Brudzewo": r"Brudzewo: ryz (\d+).*?\+ (\d+) butelek wody \+ (\d+) wiertarek",
        "Darzlubie": r"Darzlubiu.*?(\d+) porcji wolowiny, (\d+) butelek wody i (\d+) kilofow",
        "Celbowo": r"Celbowo.*?(\d+) porcji kurczaka, (\d+) butelek wody i (\d+) mlotkow",
        "Mechowo": r"Mechowo.*?ziemniaki (\d+).*?kapusta (\d+).*?marchew (\d+).*?woda (\d+).*?lopaty (\d+)",
        "Puck": r"Puck.*?(\d+) chlebow, (\d+) workow ryzu, (\d+) butelek wody i (\d+) wiertarek",
        "Karlinkowo": r"Karlinkowo.*?(\d+) makaronu, (\d+) porcje wolowiny, (\d+).*?ziemniakow, (\d+) butelek wody i (\d+) kilofow",
    }
    goods = {
        "Opalino": ("chleb", "woda", "mlotek"),
        "Domatowo": ("makaron", "woda", "lopata"),
        "Brudzewo": ("ryz", "woda", "wiertarka"),
        "Darzlubie": ("wolowina", "woda", "kilof"),
        "Celbowo": ("kurczak", "woda", "mlotek"),
        "Mechowo": ("ziemniak", "kapusta", "marchew", "woda", "lopata"),
        "Puck": ("chleb", "ryz", "woda", "wiertarka"),
        "Karlinkowo": ("makaron", "wolowina", "ziemniak", "woda", "kilof"),
    }
    result: dict[str, dict[str, int]] = {}
    for city, pattern in city_patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            raise FilesystemError(f"Missing needs declaration for {city}")
        result[city] = dict(zip(goods[city], map(int, match.groups()), strict=True))
    return result


def parse_managers(text: str) -> dict[str, str]:
    # Some names are deliberately split between neighbouring diary entries.
    candidates = {
        "Domatowo": "Natan Rams",
        "Opalino": "Iga Kapecka",
        "Brudzewo": "Rafal Kisiel",
        "Darzlubie": "Marta Frantz",
        "Celbowo": "Oskar Radtke",
        "Mechowo": "Eliza Redmann",
        "Puck": "Damian Kroll",
        "Karlinkowo": "Lena Konkel",
    }
    folded = ascii_name(text).casefold()
    missing = [name for name in candidates.values() if any(part.casefold() not in folded for part in name.split())]
    if missing:
        raise FilesystemError(f"Missing manager names: {', '.join(missing)}")
    return candidates


def parse_sales(text: str) -> dict[str, list[str]]:
    singular = {"ziemniaki": "ziemniak"}
    sales: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        parts = [part.strip() for part in raw_line.split("->")]
        if len(parts) != 3:
            continue
        city, good, _buyer = parts
        good = ascii_name(good).casefold()
        good = singular.get(good, good)
        sales.setdefault(good, []).append(ascii_name(city))
    if not sales:
        raise FilesystemError("No sales transactions found")
    return {good: sorted(set(cities)) for good, cities in sorted(sales.items())}


def parse_trade_data(payload: bytes) -> TradeData:
    notes = read_notes(payload)
    required = {"ogłoszenia.txt", "rozmowy.txt", "transakcje.txt"}
    missing = required.difference(notes)
    if missing:
        raise FilesystemError(f"Missing notes: {', '.join(sorted(missing))}")
    return TradeData(
        needs=parse_needs(ascii_name(notes["ogłoszenia.txt"])),
        managers=parse_managers(notes["rozmowy.txt"]),
        sales=parse_sales(notes["transakcje.txt"]),
    )


def build_operations(data: TradeData) -> list[dict[str, str]]:
    operations = [
        {"action": "createDirectory", "path": path}
        for path in ("/miasta", "/osoby", "/towary")
    ]
    for city, needs in sorted(data.needs.items()):
        city_file = ascii_name(city).lower()
        operations.append({
            "action": "createFile",
            "path": f"/miasta/{city_file}",
            "content": json.dumps(needs, ensure_ascii=True, separators=(",", ":")),
        })
    for city, person in sorted(data.managers.items()):
        city_file = ascii_name(city).lower()
        person_file = ascii_name(person).lower().replace(" ", "_")
        operations.append({
            "action": "createFile",
            "path": f"/osoby/{person_file}",
            "content": f"{ascii_name(person)}\n[{ascii_name(city)}](/miasta/{city_file})",
        })
    for good, cities in sorted(data.sales.items()):
        links = "\n".join(f"[{city}](/miasta/{city.lower()})" for city in cities)
        operations.append({"action": "createFile", "path": f"/towary/{good}", "content": links})
    return operations


class FilesystemWorkflow:
    def __init__(self, hub: ApiClient) -> None:
        self.hub = hub

    def call(self, answer: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Any:
        return self.hub.post_json(
            "verify", {"apikey": self.hub.api_key, "task": TASK_NAME, "answer": answer}
        )

    def help(self) -> Any:
        return self.call({"action": "help"})

    def run(self) -> dict[str, Any]:
        notes = self.hub.request_bytes(NOTES_ENDPOINT)
        data = parse_trade_data(notes)
        help_response = self.help()
        reset_response = self.call({"action": "reset"})
        batch_response = self.call(build_operations(data))
        done_response = self.call({"action": "done"})
        if not isinstance(done_response, Mapping):
            raise ApiClientError("filesystem verifier returned a non-object response")
        return {
            "help": help_response,
            "reset": reset_response,
            "batch": batch_response,
            "done": done_response,
        }
