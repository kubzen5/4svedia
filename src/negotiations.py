from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler
from src.api_client import ApiClient


DATA_ENDPOINT = "dane/s03e04_csv/"
CSV_FILES = ("cities.csv", "items.csv", "connections.csv")
MAX_RESPONSE_BYTES = 500
_UNITS = r"(?:ah|khz|mhz|ghz|kohm|mohm|ohm|pf|nf|uf|ma|mm|cm|kg|kw|mw|w|v|a|m)"
_IGNORED_WORDS = {
    "chce", "dla", "dlugosc", "dlugosci", "metra", "metrow", "potrzebny",
    "potrzebna", "potrzebne", "potrzebuje", "prosze", "szukam", "sztuka",
    "sztuki", "sztuk", "o", "do", "mi", "nam", "miec", "kupic",
}


class NegotiationsError(RuntimeError):
    """Raised for invalid source data or a query that cannot be matched."""


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    ascii_text = re.sub(rf"(\d+(?:[.,]\d+)?)\s*({_UNITS})\b", r"\1\2", ascii_text)
    return " ".join(re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", ascii_text))


def meaningful_tokens(text: str) -> set[str]:
    return {
        token for token in normalize(text).split()
        if token not in _IGNORED_WORDS and len(token) > 1
    }


@dataclass(frozen=True, slots=True)
class Match:
    item: str
    cities: tuple[str, ...]

    def output(self) -> str:
        return f"Produkt: {self.item}; miasta: {', '.join(self.cities) or 'brak'}"


class ProductIndex:
    def __init__(
        self,
        items: list[tuple[str, str]],
        city_names: dict[str, str],
        connections: dict[str, set[str]],
    ) -> None:
        if not items or not city_names:
            raise NegotiationsError("CSV data must contain products and cities")
        self._items = items
        self._city_names = city_names
        self._connections = connections

    @classmethod
    def from_csv(cls, cities: bytes, items: bytes, connections: bytes) -> "ProductIndex":
        city_rows = _read_csv(cities, ("name", "code"))
        item_rows = _read_csv(items, ("name", "code"))
        connection_rows = _read_csv(connections, ("itemCode", "cityCode"))
        city_names = {row["code"]: row["name"] for row in city_rows}
        availability: dict[str, set[str]] = {}
        for row in connection_rows:
            availability.setdefault(row["itemCode"], set()).add(row["cityCode"])
        return cls(
            [(row["name"], row["code"]) for row in item_rows],
            city_names,
            availability,
        )

    @classmethod
    def download(cls, client: ApiClient) -> "ProductIndex":
        payloads = {
            name: client.request_bytes(f"{DATA_ENDPOINT}{name}") for name in CSV_FILES
        }
        return cls.from_csv(
            payloads["cities.csv"], payloads["items.csv"], payloads["connections.csv"]
        )

    def search(self, query: str) -> Match:
        query = query.strip()
        query_tokens = meaningful_tokens(query)
        if not query_tokens:
            raise NegotiationsError("Podaj naturalny opis jednego produktu")

        ranked: list[tuple[float, str, str]] = []
        normalized_query = normalize(query)
        for name, code in self._items:
            normalized_name = normalize(name)
            name_tokens = set(normalized_name.split())
            overlap = query_tokens & name_tokens
            coverage = len(overlap) / len(name_tokens)
            precision = len(overlap) / len(query_tokens)
            sequence = SequenceMatcher(None, normalized_query, normalized_name).ratio()
            # Exact numeric/model tokens are the strongest disambiguators in this catalog.
            query_specs = {token for token in query_tokens if any(c.isdigit() for c in token)}
            spec_score = len(query_specs & name_tokens) / max(1, len(query_specs))
            score = 0.40 * coverage + 0.25 * precision + 0.20 * sequence + 0.15 * spec_score
            ranked.append((score, name, code))

        score, name, code = max(ranked, key=lambda value: (value[0], value[1]))
        if score < 0.22:
            raise NegotiationsError("Nie znaleziono wiarygodnego dopasowania produktu")
        cities = tuple(
            sorted(
                self._city_names[city_code]
                for city_code in self._connections.get(code, set())
                if city_code in self._city_names
            )
        )
        return Match(name, cities)


def _read_csv(payload: bytes, required: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NegotiationsError("CSV is not valid UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
        raise NegotiationsError(f"CSV is missing columns: {', '.join(required)}")
    rows = [{key: (row.get(key) or "").strip() for key in required} for row in reader]
    if any(not all(row.values()) for row in rows):
        raise NegotiationsError("CSV contains an incomplete row")
    return rows


def make_handler(index: ProductIndex) -> type[BaseHTTPRequestHandler]:
    class NegotiationsHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path.rstrip("/") not in ("", "/search"):
                self._json(404, {"output": "Nie znaleziono narzędzia"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 10_000:
                    raise ValueError("Nieprawidłowy rozmiar zapytania")
                payload = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("params"), str):
                    raise ValueError("Pole params musi być tekstem")
                self._json(200, {"output": index.search(payload["params"]).output()})
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, NegotiationsError) as exc:
                self._json(400, {"output": f"Błąd: {exc}"})

        def do_GET(self) -> None:
            if self.path.rstrip("/") in ("", "/health", "/search"):
                self._json(200, {"status": "ok"})
            else:
                self._json(404, {"output": "Nie znaleziono narzędzia"})

        def _json(self, status: int, payload: dict[str, str]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_RESPONSE_BYTES:
                body = b'{"output":"Blad: odpowiedz przekracza limit 500 bajtow"}'
                status = 500
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return NegotiationsHandler
