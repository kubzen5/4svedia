from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.api_client import ApiClient, ApiClientError


class SaveThemError(RuntimeError):
    """Raised when mission data is incomplete or no feasible route exists."""


@dataclass(frozen=True, slots=True)
class Vehicle:
    name: str
    fuel_per_move: int
    food_per_move: int

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Vehicle":
        consumption = payload.get("consumption")
        if not isinstance(consumption, Mapping):
            raise SaveThemError("Vehicle response has no consumption object")
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise SaveThemError("Vehicle response has no name")
        try:
            # Tenths keep resource calculations exact (for example 0.7 and 0.1).
            fuel = round(float(consumption["fuel"]) * 10)
            food = round(float(consumption["food"]) * 10)
        except (KeyError, TypeError, ValueError) as exc:
            raise SaveThemError("Vehicle consumption is invalid") from exc
        return cls(name=name, fuel_per_move=fuel, food_per_move=food)


@dataclass(frozen=True, slots=True)
class Route:
    vehicle: str
    actions: tuple[str, ...]
    fuel_used: int
    food_used: int

    @property
    def answer(self) -> list[str]:
        return [self.vehicle, *self.actions]


class MissionTools:
    """Discover and call the task APIs using their advertised contracts."""

    def __init__(self, hub: ApiClient) -> None:
        self.hub = hub

    def discover(self, query: str, expected_name: str) -> str:
        response = self.hub.post_json(
            "api/toolsearch", {"apikey": self.hub.api_key, "query": query}
        )
        if not isinstance(response, Mapping) or not isinstance(response.get("tools"), list):
            raise SaveThemError("toolsearch returned an invalid response")
        for tool in response["tools"]:
            if isinstance(tool, Mapping) and tool.get("name") == expected_name:
                url = tool.get("url")
                if isinstance(url, str) and url:
                    return url
        raise SaveThemError(f"toolsearch did not find the {expected_name!r} tool")

    def call(self, endpoint: str, query: str) -> Mapping[str, Any]:
        response = self.hub.post_json(
            endpoint, {"apikey": self.hub.api_key, "query": query}
        )
        if not isinstance(response, Mapping):
            raise SaveThemError(f"Tool {endpoint} returned a non-object response")
        return response

    def load_mission(self, city: str) -> tuple[list[list[str]], list[Vehicle]]:
        maps = self.discover("map terrain", "maps")
        vehicles_api = self.discover("vehicles fuel food", "wehicles")
        # The maps service currently normalizes lower-case queries reliably.
        map_response = self.call(maps, city.casefold())
        grid = validate_grid(map_response.get("map"))
        vehicles = [
            Vehicle.from_api(self.call(vehicles_api, name))
            for name in ("rocket", "horse", "walk", "car")
        ]
        return grid, vehicles


def validate_grid(value: Any) -> list[list[str]]:
    if not isinstance(value, list) or len(value) != 10:
        raise SaveThemError("Map must contain exactly 10 rows")
    grid: list[list[str]] = []
    for row in value:
        if not isinstance(row, list) or len(row) != 10 or not all(
            isinstance(cell, str) and len(cell) == 1 for cell in row
        ):
            raise SaveThemError("Every map row must contain 10 one-character cells")
        grid.append(list(row))
    if sum(cell == "S" for row in grid for cell in row) != 1:
        raise SaveThemError("Map must contain one start marker")
    if sum(cell == "G" for row in grid for cell in row) != 1:
        raise SaveThemError("Map must contain one goal marker")
    return grid


_DIRECTIONS = (
    ("up", -1, 0),
    ("right", 0, 1),
    ("down", 1, 0),
    ("left", 0, -1),
)


def _find(grid: Sequence[Sequence[str]], marker: str) -> tuple[int, int]:
    return next(
        (row, column)
        for row, cells in enumerate(grid)
        for column, cell in enumerate(cells)
        if cell == marker
    )


def _can_enter(cell: str, mode: str) -> bool:
    if cell == "R":
        return False
    if cell == "W":
        return mode in {"horse", "walk"}
    return True


def plan_route(
    grid: Sequence[Sequence[str]],
    vehicles: Iterable[Vehicle],
    *,
    fuel_limit: int = 100,
    food_limit: int = 100,
) -> Route:
    """Find the fastest feasible route, then minimize fuel among equal times."""

    vehicle_by_name = {vehicle.name: vehicle for vehicle in vehicles}
    walk = vehicle_by_name.get("walk")
    if walk is None:
        raise SaveThemError("Walking parameters are required for dismounting")
    start, goal = _find(grid, "S"), _find(grid, "G")

    # priority: elapsed time (food), moves, fuel, deterministic insertion order
    queue: list[tuple[int, int, int, int, tuple[Any, ...]]] = []
    serial = 0
    best: dict[tuple[int, int, str, int, int], tuple[int, int]] = {}
    for vehicle in vehicle_by_name.values():
        if vehicle.name == "walk":
            continue
        state = (start[0], start[1], vehicle.name, 0, 0, vehicle.name, ())
        heapq.heappush(queue, (0, 0, 0, serial, state))
        serial += 1

    while queue:
        food, moves, fuel, _, state = heapq.heappop(queue)
        row, column, mode, _, _, initial, actions = state
        key = (row, column, mode, fuel, food)
        if best.get(key, (10**9, 10**9)) < (food, moves):
            continue
        if (row, column) == goal:
            return Route(initial, actions, fuel, food)

        current = vehicle_by_name[mode]
        for action, row_delta, column_delta in _DIRECTIONS:
            next_row, next_column = row + row_delta, column + column_delta
            if not (0 <= next_row < len(grid) and 0 <= next_column < len(grid[0])):
                continue
            if not _can_enter(grid[next_row][next_column], mode):
                continue
            next_fuel = fuel + current.fuel_per_move
            next_food = food + current.food_per_move
            if next_fuel > fuel_limit or next_food > food_limit:
                continue
            next_key = (next_row, next_column, mode, next_fuel, next_food)
            score = (next_food, moves + 1)
            if score >= best.get(next_key, (10**9, 10**9)):
                continue
            best[next_key] = score
            next_state = (
                next_row, next_column, mode, next_fuel, next_food,
                initial, (*actions, action),
            )
            heapq.heappush(
                queue, (next_food, moves + 1, next_fuel, serial, next_state)
            )
            serial += 1

        if mode != "walk":
            next_key = (row, column, "walk", fuel, food)
            score = (food, moves)
            if score < best.get(next_key, (10**9, 10**9)):
                best[next_key] = score
                next_state = (row, column, "walk", fuel, food, initial, (*actions, "dismount"))
                heapq.heappush(queue, (food, moves, fuel, serial, next_state))
                serial += 1

    raise SaveThemError("No route fits the available fuel and food")


def verify(hub: ApiClient, route: Route) -> Mapping[str, Any]:
    response = hub.post_json(
        "verify",
        {"apikey": hub.api_key, "task": "savethem", "answer": route.answer},
    )
    if not isinstance(response, Mapping):
        raise ApiClientError("Verification returned a non-object response")
    return response
