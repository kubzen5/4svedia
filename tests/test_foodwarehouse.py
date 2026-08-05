import unittest

from src.foodwarehouse import (
    FoodWarehouseError,
    destination_map,
    normalized_items,
    parse_city_needs,
    select_creator,
)


class FoodWarehouseTests(unittest.TestCase):
    def test_parses_city_needs_without_changing_names(self):
        needs = parse_city_needs({"Toruń": {"woda": 120, "młotek": 6}})
        self.assertEqual(needs[0].city, "Toruń")
        self.assertEqual(needs[0].items, {"woda": 120, "młotek": 6})

    def test_rejects_boolean_zero_and_empty_item_maps(self):
        for payload in (
            {"Toruń": {"woda": True}},
            {"Toruń": {"woda": 0}},
            {"Toruń": {}},
        ):
            with self.subTest(payload=payload), self.assertRaises(FoodWarehouseError):
                parse_city_needs(payload)

    def test_maps_destinations_and_selects_transport_creator(self):
        needs = parse_city_needs({"opalino": {"woda": 1}})
        destinations = destination_map(
            {"rows": [{"destination_id": 991828, "name": "Opalino"}]}, needs
        )
        creator = select_creator({
            "rows": [{"user_id": 2, "login": "operator", "birthday": "1991-04-06"}]
        })
        self.assertEqual(destinations, {"opalino": 991828})
        self.assertEqual(creator.user_id, 2)

    def test_normalizes_item_list_and_sums_duplicates(self):
        self.assertEqual(
            normalized_items([
                {"name": "woda", "items": 2},
                {"name": "woda", "items": 3},
            ]),
            {"woda": 5},
        )


if __name__ == "__main__":
    unittest.main()
