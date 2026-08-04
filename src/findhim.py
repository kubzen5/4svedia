from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


class FindHimDataError(ValueError):
    """Raised when the findhim API returns an unsupported payload."""


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class PowerPlant:
    code: str
    name: str
    coordinates: Coordinates


@dataclass(frozen=True, slots=True)
class PersonLocation:
    name: str
    surname: str
    access_level: int | str
    coordinates: Coordinates


@dataclass(frozen=True, slots=True)
class Match:
    person: PersonLocation
    power_plant: PowerPlant
    distance_km: float


def _items(payload: Any, keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, Mapping):
        values = next((payload[key] for key in keys if isinstance(payload.get(key), list)), None)
        if values is None:
            values = [payload]
    else:
        raise FindHimDataError("JSON must be an object or a list")

    if not all(isinstance(item, Mapping) for item in values):
        raise FindHimDataError("JSON list must contain objects")
    return list(values)


def _value(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _coordinates(item: Mapping[str, Any]) -> Coordinates:
    nested = _value(item, "coordinates", "location", "position")
    source = nested if isinstance(nested, Mapping) else item
    latitude = _value(source, "latitude", "lat")
    longitude = _value(source, "longitude", "lon", "lng")
    try:
        result = Coordinates(float(latitude), float(longitude))
    except (TypeError, ValueError) as exc:
        raise FindHimDataError("Missing or invalid latitude/longitude") from exc
    if not (-90 <= result.latitude <= 90 and -180 <= result.longitude <= 180):
        raise FindHimDataError("Coordinates are outside valid ranges")
    return result


def parse_power_plants(payload: Any) -> list[PowerPlant]:
    # The current endpoint returns a city-keyed mapping without coordinates,
    # despite the task description promising coordinates. Keep this fallback
    # local and use coordinates from the payload whenever the API adds them.
    city_coordinates = {
        "zabrze": Coordinates(50.3249, 18.7857),
        "piotrków trybunalski": Coordinates(51.4052, 19.7030),
        "grudzišdz": Coordinates(53.4837, 18.7536),
        "grudziądz": Coordinates(53.4837, 18.7536),
        "tczew": Coordinates(54.0919, 18.7773),
        "radom": Coordinates(51.4027, 21.1471),
        "chelmno": Coordinates(53.3486, 18.4251),
        "chełmno": Coordinates(53.3486, 18.4251),
        "żarnowiec": Coordinates(54.7890, 18.0860),
    }
    if isinstance(payload, Mapping) and isinstance(payload.get("power_plants"), Mapping):
        source = payload["power_plants"]
        normalized: list[Mapping[str, Any]] = []
        for city, details in source.items():
            if not isinstance(details, Mapping):
                raise FindHimDataError("Power plant details must be an object")
            normalized.append({"name": city, **details})
        items = normalized
    else:
        items = _items(payload, ("locations", "powerPlants", "power_plants", "plants"))

    plants: list[PowerPlant] = []
    for item in items:
        code = _value(item, "code", "id", "locationCode")
        name = _value(item, "name", "powerPlant", "power_plant", "city")
        if code is None or name is None:
            raise FindHimDataError("Power plant requires code and name")
        try:
            coordinates = _coordinates(item)
        except FindHimDataError:
            coordinates = city_coordinates.get(str(name).strip().casefold())
            if coordinates is None:
                raise FindHimDataError(
                    f"Missing coordinates for power plant city: {name}"
                ) from None
        plants.append(PowerPlant(str(code), str(name), coordinates))
    if not plants:
        raise FindHimDataError("Power plant list is empty")
    return plants


def parse_person_locations(payload: Any, *, name: str, surname: str) -> list[PersonLocation]:
    items = _items(payload, ("people", "results", "locations", "data"))
    if not items:
        raise FindHimDataError(f"Location list is empty for {name} {surname}")
    return [PersonLocation(name, surname, 0, _coordinates(item)) for item in items]


def parse_access_level(payload: Any) -> int | str:
    item = _items(payload, ("people", "results", "data"))[0]
    access_level = _value(item, "accessLevel", "access_level", "access", "level")
    if access_level is None:
        raise FindHimDataError("Access-level response does not contain accessLevel")
    return access_level


def distance_km(first: Coordinates, second: Coordinates) -> float:
    """Return great-circle distance using the haversine formula."""
    radius_km = 6371.0088
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second.longitude - first.longitude)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def find_nearby_match(
    people: Iterable[PersonLocation],
    plants: Iterable[PowerPlant],
    *,
    maximum_distance_km: float,
) -> Match:
    if maximum_distance_km <= 0:
        raise ValueError("maximum_distance_km must be greater than zero")
    candidates = [
        Match(person, plant, distance_km(person.coordinates, plant.coordinates))
        for person in people
        for plant in plants
    ]
    nearby = [match for match in candidates if match.distance_km <= maximum_distance_km]
    if not nearby:
        raise FindHimDataError(
            f"No person found within {maximum_distance_km:g} km of a power plant"
        )
    nearby.sort(key=lambda match: match.distance_km)
    return nearby[0]


def build_answer(match: Match) -> dict[str, Any]:
    return {
        "name": match.person.name,
        "surname": match.person.surname,
        "accessLevel": match.person.access_level,
        "powerPlant": match.power_plant.code,
    }
