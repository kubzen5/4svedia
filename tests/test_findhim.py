import unittest

from src.findhim import (
    Coordinates,
    PersonLocation,
    PowerPlant,
    build_answer,
    distance_km,
    find_nearby_match,
    parse_access_level,
    parse_person_locations,
    parse_power_plants,
)


class FindHimTests(unittest.TestCase):
    def test_parses_common_payload_shapes(self) -> None:
        plants = parse_power_plants(
            {"locations": [{"code": "ZAR", "name": "Zarnowiec", "lat": 54.7, "lon": 18.1}]}
        )
        people = parse_person_locations(
            {"data": [{"coordinates": {"latitude": 54.7001, "longitude": 18.1}}]},
            name="Jan",
            surname="Kowalski",
        )
        self.assertEqual(plants[0].code, "ZAR")
        self.assertEqual(people[0].coordinates.latitude, 54.7001)
        self.assertEqual(parse_access_level({"accessLevel": 4}), 4)

    def test_parses_real_city_keyed_power_plant_shape(self) -> None:
        plants = parse_power_plants(
            {"power_plants": {"Chelmno": {"code": "PWR2758PL", "is_active": True}}}
        )
        self.assertEqual(plants[0].code, "PWR2758PL")
        self.assertAlmostEqual(plants[0].coordinates.latitude, 53.3486)

    def test_finds_one_nearby_person_and_builds_answer(self) -> None:
        plant = PowerPlant("ZAR", "Zarnowiec", Coordinates(54.7, 18.1))
        nearby = PersonLocation("Jan", "Kowalski", 4, Coordinates(54.701, 18.1))
        far = PersonLocation("Adam", "Nowak", 1, Coordinates(52.2, 21.0))
        match = find_nearby_match([nearby, far], [plant], maximum_distance_km=10)
        self.assertLess(match.distance_km, 1)
        self.assertEqual(
            build_answer(match),
            {"name": "Jan", "surname": "Kowalski", "accessLevel": 4, "powerPlant": "ZAR"},
        )

    def test_haversine_distance(self) -> None:
        result = distance_km(Coordinates(52.2297, 21.0122), Coordinates(50.0647, 19.9450))
        self.assertAlmostEqual(result, 252.0, delta=2.0)


if __name__ == "__main__":
    unittest.main()
