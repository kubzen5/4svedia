from __future__ import annotations

import unittest

from src.domatowo import (
    Unit, assign_nearest, block3_coordinates, contains_survivor, parse_units,
    survivor_field,
)


class DomatowoTests(unittest.TestCase):
    def test_extracts_block_coordinates(self) -> None:
        response = {"map": {"grid": [["empty", "block3"], ["block3", "road"]]}}
        self.assertEqual(block3_coordinates(response), ["B1", "A2"])

    def test_assigns_every_target_once(self) -> None:
        scouts = [Unit("one", "scout", "E2"), Unit("two", "scout", "B9")]
        routes = assign_nearest(scouts, ["F1", "G2", "A10", "B11"])
        assigned = [target for route in routes.values() for target in route]
        self.assertCountEqual(assigned, ["F1", "G2", "A10", "B11"])
        self.assertEqual(routes["one"][0], "F1")
        self.assertEqual(routes["two"][0], "A10")

    def test_survivor_detection_rejects_negative_log(self) -> None:
        self.assertFalse(contains_survivor({"message": "No human found here"}))
        self.assertTrue(contains_survivor({"humanFound": True}))
        self.assertTrue(contains_survivor({"message": "Survivor found!"}))
        self.assertTrue(contains_survivor({
            "msg": "Potwierdzam odnalezienie osoby. Mężczyzna siedzi za piecem."
        }))
        self.assertFalse(contains_survivor({"msg": "Nie odnaleziono osoby."}))
        self.assertFalse(contains_survivor({"msg": "Brak obecności człowieka."}))
        self.assertTrue(contains_survivor({"msg": "Jest tutaj osoba. Mężczyzna jest ranny."}))
        self.assertTrue(contains_survivor({
            "msg": "Ruszył się i go wypatrzyliśmy. Mężczyzna ukryty w cieniu."
        }))
        self.assertEqual(survivor_field({"logs": [
            {"msg": "Nie odnaleziono człowieka.", "field": "C10"},
            {"msg": "Jest tutaj osoba.", "field": "F2"},
        ]}), "F2")

    def test_parses_polish_type_field_returned_by_api(self) -> None:
        response = {"objects": [{"typ": "transporter", "position": "A6", "id": "abc"}]}
        self.assertEqual(parse_units(response), [Unit("abc", "transporter", "A6")])


if __name__ == "__main__":
    unittest.main()
