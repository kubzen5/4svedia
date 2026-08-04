from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.api_client import ApiClient, ApiClientError


DIRECTIONS = ("N", "E", "S", "W")
DELTAS = {"N": (-1, 0), "E": (0, 1), "S": (1, 0), "W": (0, -1)}
OPPOSITE = {"N": "S", "E": "W", "S": "N", "W": "E"}
TARGET_CODES = ((3, 5, 4), (1, 2, 5), (9, 7, 0))
# Codes are sprite orientations. Each tuple lists successive clockwise rotations.
CODE_CYCLES = ((0,), (1, 4), (2, 5, 3, 6), (7, 8, 9, 10))
ALIASES = {
    "N": "N", "NORTH": "N", "TOP": "N", "UP": "N", "GORA": "N", "GÓRA": "N",
    "E": "E", "EAST": "E", "RIGHT": "E", "PRAWO": "E",
    "S": "S", "SOUTH": "S", "BOTTOM": "S", "DOWN": "S", "DOL": "S", "DÓŁ": "S",
    "W": "W", "WEST": "W", "LEFT": "W", "LEWO": "W",
}


@dataclass(frozen=True, slots=True)
class Tile:
    row: int
    column: int
    connectors: frozenset[str]
    label: str | None = None

    @property
    def address(self) -> str:
        return f"{self.row + 1}x{self.column + 1}"


def rotate(connectors: Iterable[str], turns: int) -> frozenset[str]:
    return frozenset(DIRECTIONS[(DIRECTIONS.index(item) + turns) % 4] for item in connectors)


def _directions(value: Any) -> frozenset[str] | None:
    if isinstance(value, str):
        chunks = value.replace(",", " ").replace("|", " ").replace("-", " ").split()
        parsed = [ALIASES.get(chunk.strip().upper()) for chunk in chunks]
        if chunks and all(parsed):
            return frozenset(parsed)  # type: ignore[arg-type]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        parsed = [ALIASES.get(str(item).strip().upper()) for item in value]
        if value and all(parsed):
            return frozenset(parsed)  # type: ignore[arg-type]
    return None


def _find_connectors(tile: Mapping[str, Any]) -> frozenset[str]:
    preferred = ("connectors", "connections", "directions", "edges", "cables", "ports")
    for key in preferred:
        if key in tile and (result := _directions(tile[key])) is not None:
            return result
    boolean_edges = {ALIASES.get(str(key).upper()) for key, value in tile.items() if value is True}
    result = frozenset(edge for edge in boolean_edges if edge)
    if result:
        return result
    raise ValueError(f"Cannot find cable directions in tile: {sorted(tile)}")


def parse_board(payload: Any) -> tuple[Tile, ...]:
    """Normalize common 3x3 JSON board shapes into row-major tiles."""
    if isinstance(payload, Mapping):
        for key in ("board", "grid", "tiles", "data"):
            if key in payload:
                payload = payload[key]
                break

    entries: list[tuple[int, int, Mapping[str, Any]]] = []
    if isinstance(payload, Mapping):
        for address, tile in payload.items():
            if not isinstance(tile, Mapping) or "x" not in str(address).lower():
                continue
            row_text, column_text = str(address).lower().split("x", 1)
            entries.append((int(row_text) - 1, int(column_text) - 1, tile))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        flat = list(payload)
        if len(flat) == 3 and all(isinstance(row, Sequence) and len(row) == 3 for row in flat):
            entries = [(r, c, tile) for r, row in enumerate(flat) for c, tile in enumerate(row) if isinstance(tile, Mapping)]
        else:
            for index, tile in enumerate(flat):
                if not isinstance(tile, Mapping):
                    continue
                row = int(tile.get("row", tile.get("r", index // 3 + 1))) - 1
                column = int(tile.get("column", tile.get("col", tile.get("c", index % 3 + 1)))) - 1
                entries.append((row, column, tile))

    if len(entries) != 9 or {(r, c) for r, c, _ in entries} != {(r, c) for r in range(3) for c in range(3)}:
        raise ValueError("Electricity board must contain exactly nine uniquely positioned tiles")
    tiles = [Tile(r, c, _find_connectors(tile), str(tile.get("label") or tile.get("name") or tile.get("type") or "") or None) for r, c, tile in entries]
    return tuple(sorted(tiles, key=lambda tile: (tile.row, tile.column)))


def parse_codes(payload: Any) -> tuple[tuple[int, ...], ...]:
    if isinstance(payload, Mapping):
        for key in ("board", "grid", "data"):
            if key in payload:
                payload = payload[key]
                break
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)) or len(payload) != 3:
        raise ValueError("Electricity JSON must be a 3x3 matrix")
    rows: list[tuple[int, ...]] = []
    for row in payload:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 3:
            raise ValueError("Electricity JSON must be a 3x3 matrix")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in row):
            raise ValueError("Electricity matrix values must be integers")
        rows.append(tuple(row))
    return tuple(rows)


def solve_codes(board: Sequence[Sequence[int]]) -> dict[str, int]:
    """Calculate clockwise rotations from Hub sprite codes to the published goal."""
    cycle_by_code = {code: cycle for cycle in CODE_CYCLES for code in cycle}
    rotations: dict[str, int] = {}
    for row in range(3):
        for column in range(3):
            current, target = board[row][column], TARGET_CODES[row][column]
            try:
                cycle = cycle_by_code[current]
            except KeyError as exc:
                raise ValueError(f"Unknown electricity tile code: {current}") from exc
            if target not in cycle:
                raise ValueError(f"Tile {row + 1}x{column + 1} cannot rotate from code {current} to {target}")
            rotations[f"{row + 1}x{column + 1}"] = (cycle.index(target) - cycle.index(current)) % len(cycle)
    return rotations


def solve_board(tiles: Sequence[Tile]) -> dict[str, int]:
    """Find the minimum clockwise rotations forming one closed connected network."""
    by_position = {(tile.row, tile.column): tile for tile in tiles}
    if set(by_position) != {(r, c) for r in range(3) for c in range(3)}:
        raise ValueError("Expected a complete 3x3 board")
    options = {position: sorted({(rotate(tile.connectors, turns), turns) for turns in range(4)}, key=lambda x: x[1]) for position, tile in by_position.items()}
    positions = [(r, c) for r in range(3) for c in range(3)]
    best: tuple[int, dict[tuple[int, int], tuple[frozenset[str], int]]] | None = None

    def search(index: int, chosen: dict[tuple[int, int], tuple[frozenset[str], int]], cost: int) -> None:
        nonlocal best
        if best and cost >= best[0]:
            return
        if index == len(positions):
            start = positions[0]
            seen = {start}
            queue = deque([start])
            while queue:
                position = queue.popleft()
                for direction in chosen[position][0]:
                    dr, dc = DELTAS[direction]
                    neighbor = (position[0] + dr, position[1] + dc)
                    if neighbor not in seen:
                        seen.add(neighbor); queue.append(neighbor)
            if len(seen) == 9:
                best = (cost, chosen.copy())
            return
        position = positions[index]
        row, column = position
        for connectors, turns in options[position]:
            valid = True
            for direction in connectors:
                dr, dc = DELTAS[direction]
                neighbor = (row + dr, column + dc)
                if neighbor not in by_position:
                    valid = False; break
                if neighbor in chosen and OPPOSITE[direction] not in chosen[neighbor][0]:
                    valid = False; break
            if valid:
                for direction, neighbor in (("N", (row - 1, column)), ("W", (row, column - 1))):
                    if neighbor in chosen and (OPPOSITE[direction] in chosen[neighbor][0]) != (direction in connectors):
                        valid = False; break
            if valid:
                chosen[position] = (connectors, turns)
                search(index + 1, chosen, cost + turns)
                del chosen[position]

    search(0, {}, 0)
    if best is None:
        raise ValueError("No closed connected configuration exists for this board")
    return {by_position[position].address: value[1] for position, value in best[1].items()}


class ElectricityClient:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def fetch_board(self) -> tuple[tuple[int, ...], ...]:
        return parse_codes(self.client.get_json(f"data/{self.client.api_key}/electricity.json"))

    def reset(self) -> None:
        self.client.request_bytes(f"data/{self.client.api_key}/electricity.png", query={"reset": 1})

    def rotate(self, address: str) -> Any:
        return self.client.post_json("verify", {"apikey": self.client.api_key, "task": "electricity", "answer": {"rotate": address}})

    def solve(self, *, reset: bool = False) -> Any:
        if reset:
            self.reset()
        rotations = solve_codes(self.fetch_board())
        response: Any = None
        for address, count in rotations.items():
            for _ in range(count):
                response = self.rotate(address)
                if "{FLG:" in str(response):
                    return response
        if response is None:
            return {"code": 0, "message": "Board is already solved"}
        return response
