from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.api_client import ApiClient, ApiClientError


TASK_NAME = "foodwarehouse"
CITIES_ENDPOINT = "dane/food4cities.json"


class FoodWarehouseError(ValueError):
    """Raised when warehouse data or API responses are malformed."""


@dataclass(frozen=True, slots=True)
class CityNeed:
    city: str
    items: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class Creator:
    user_id: int
    login: str
    birthday: str


def response_rows(response: Any, context: str) -> list[Mapping[str, Any]]:
    if not isinstance(response, Mapping) or not isinstance(response.get("rows"), list):
        raise FoodWarehouseError(f"{context} response does not contain rows")
    rows = response["rows"]
    if not all(isinstance(row, Mapping) for row in rows):
        raise FoodWarehouseError(f"{context} response contains an invalid row")
    return rows


def destination_map(response: Any, cities: Sequence[CityNeed]) -> dict[str, int]:
    destinations: dict[str, int] = {}
    for row in response_rows(response, "destinations"):
        name, destination_id = row.get("name"), row.get("destination_id")
        if isinstance(name, str) and isinstance(destination_id, int):
            destinations[name.casefold()] = destination_id
    missing = [need.city for need in cities if need.city.casefold() not in destinations]
    if missing:
        raise FoodWarehouseError(f"missing destination codes for: {', '.join(missing)}")
    return destinations


def select_creator(response: Any) -> Creator:
    rows = response_rows(response, "users")
    if not rows:
        raise FoodWarehouseError("no active transport user found")
    row = rows[0]
    user_id, login, birthday = row.get("user_id"), row.get("login"), row.get("birthday")
    if not isinstance(user_id, int) or not isinstance(login, str) or not isinstance(birthday, str):
        raise FoodWarehouseError("transport user has incomplete authentication data")
    return Creator(user_id, login, birthday)


def object_field(response: Any, fields: Sequence[str], context: str) -> Any:
    if not isinstance(response, Mapping):
        raise FoodWarehouseError(f"{context} returned a non-object response")
    for field in fields:
        if field in response:
            return response[field]
    for nested in response.values():
        if isinstance(nested, Mapping):
            for field in fields:
                if field in nested:
                    return nested[field]
    raise FoodWarehouseError(f"{context} response lacks {', '.join(fields)}")


def normalized_items(raw_items: Any) -> dict[str, int]:
    if not isinstance(raw_items, list):
        raise FoodWarehouseError("order items must be a list")
    result: dict[str, int] = {}
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise FoodWarehouseError("order contains an invalid item")
        name, count = item.get("name"), item.get("items")
        if not isinstance(name, str) or not isinstance(count, int):
            raise FoodWarehouseError("order contains an incomplete item")
        result[name] = result.get(name, 0) + count
    return result


def parse_city_needs(payload: Any) -> list[CityNeed]:
    if not isinstance(payload, Mapping) or not payload:
        raise FoodWarehouseError("city-needs document must be a non-empty object")

    result: list[CityNeed] = []
    for raw_city, raw_items in payload.items():
        if not isinstance(raw_city, str) or not raw_city.strip():
            raise FoodWarehouseError("every city name must be a non-empty string")
        if not isinstance(raw_items, Mapping) or not raw_items:
            raise FoodWarehouseError(f"needs for {raw_city!r} must be a non-empty object")
        items: dict[str, int] = {}
        for raw_name, raw_count in raw_items.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise FoodWarehouseError(f"invalid item name for {raw_city}")
            if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
                raise FoodWarehouseError(
                    f"quantity of {raw_name!r} for {raw_city} must be a positive integer"
                )
            items[raw_name.strip()] = raw_count
        result.append(CityNeed(raw_city.strip(), items))
    return result


class FoodWarehouseWorkflow:
    def __init__(self, hub: ApiClient) -> None:
        self.hub = hub

    def call(self, answer: Mapping[str, Any]) -> Any:
        return self.hub.post_json(
            "verify",
            {"apikey": self.hub.api_key, "task": TASK_NAME, "answer": answer},
        )

    def inspect(self) -> dict[str, Any]:
        needs_payload = self.hub.get_json(CITIES_ENDPOINT)
        needs = parse_city_needs(needs_payload)
        table_names = ("destinations", "roles", "users")
        return {
            "help": self.call({"tool": "help"}),
            "cities": [{"city": need.city, "items": dict(need.items)} for need in needs],
            "tables": self.call({"tool": "database", "query": "show tables"}),
            "schemas": {
                table: self.call(
                    {"tool": "database", "query": f"show create table {table}"}
                )
                for table in table_names
            },
            "records": {
                table: self.call({"tool": "database", "query": f"select * from {table}"})
                for table in table_names
            },
            "orders": self.call({"tool": "orders", "action": "get"}),
        }

    def run(self) -> dict[str, Any]:
        needs = parse_city_needs(self.hub.get_json(CITIES_ENDPOINT))
        quoted_cities = ",".join(f"'{need.city.casefold()}'" for need in needs)
        destinations_response = self.call({
            "tool": "database",
            "query": (
                "select destination_id, name from destinations "
                f"where lower(name) in ({quoted_cities})"
            ),
        })
        destinations = destination_map(destinations_response, needs)
        creator = select_creator(self.call({
            "tool": "database",
            "query": (
                "select user_id, login, birthday from users "
                "where role = 2 and is_active = 1 order by user_id limit 1"
            ),
        }))

        reset_response = self.call({"tool": "reset"})
        seeded = self.call({"tool": "orders", "action": "get"})
        seeded_orders = object_field(seeded, ("orders",), "orders.get")
        if not isinstance(seeded_orders, list):
            raise FoodWarehouseError("orders.get returned an invalid order list")
        deleted: list[Any] = []
        for order in seeded_orders:
            if not isinstance(order, Mapping) or not isinstance(order.get("id"), str):
                raise FoodWarehouseError("orders.get returned an invalid seeded order")
            deleted.append(self.call({"tool": "orders", "action": "delete", "id": order["id"]}))

        created: list[dict[str, Any]] = []
        for need in needs:
            destination = destinations[need.city.casefold()]
            signature_response = self.call({
                "tool": "signatureGenerator",
                "action": "generate",
                "login": creator.login,
                "birthday": creator.birthday,
                "destination": destination,
            })
            signature = object_field(
                signature_response, ("signature", "hash"), "signatureGenerator"
            )
            if not isinstance(signature, str) or len(signature) != 40:
                raise FoodWarehouseError(f"invalid signature generated for {need.city}")
            create_response = self.call({
                "tool": "orders",
                "action": "create",
                "title": f"Dostawa dla {need.city.title()}",
                "creatorID": creator.user_id,
                "destination": destination,
                "signature": signature,
            })
            order_id = object_field(create_response, ("id", "orderID", "orderId"), "orders.create")
            if not isinstance(order_id, str):
                raise FoodWarehouseError(f"invalid order identifier for {need.city}")
            self.call({
                "tool": "orders",
                "action": "append",
                "id": order_id,
                "items": dict(need.items),
            })
            created.append({
                "city": need.city,
                "destination": destination,
                "id": order_id,
                "items": dict(need.items),
            })

        final_orders_response = self.call({"tool": "orders", "action": "get"})
        final_orders = object_field(final_orders_response, ("orders",), "orders.get")
        expected_by_destination = {
            destinations[need.city.casefold()]: dict(need.items) for need in needs
        }
        actual_by_destination: dict[int, dict[str, int]] = {}
        relevant_orders = 0
        if not isinstance(final_orders, list):
            raise FoodWarehouseError("orders.get returned invalid final order data")
        for order in final_orders:
            if not isinstance(order, Mapping) or not isinstance(order.get("destination"), int):
                raise FoodWarehouseError("final order contains an invalid destination")
            if order["destination"] not in expected_by_destination:
                continue
            relevant_orders += 1
            if order["destination"] in actual_by_destination:
                raise FoodWarehouseError("multiple final orders target the same required city")
            actual_by_destination[order["destination"]] = normalized_items(order.get("items"))
        if relevant_orders != len(needs) or actual_by_destination != expected_by_destination:
            raise FoodWarehouseError("final orders do not exactly match city needs")

        done_response = self.call({"tool": "done"})
        if not isinstance(done_response, Mapping):
            raise ApiClientError("foodwarehouse verifier returned a non-object response")
        return {
            "reset": (
                {key: reset_response[key] for key in ("code", "message") if key in reset_response}
                if isinstance(reset_response, Mapping)
                else "completed"
            ),
            "deletedSeedOrders": len(deleted),
            "createdOrders": created,
            "done": done_response,
        }
