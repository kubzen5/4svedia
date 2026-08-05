import unittest

from src.savethem import SaveThemError, Vehicle, plan_route, validate_grid


MAP = [list(row) for row in (
    "........WW",
    ".......WW.",
    ".T....WW..",
    "......W...",
    "..T...W.G.",
    "....R.W...",
    "...RR.WW..",
    "SR.....W..",
    "......WW..",
    ".....WW...",
)]
VEHICLES = [
    Vehicle("rocket", 10, 1),
    Vehicle("horse", 0, 16),
    Vehicle("walk", 0, 25),
    Vehicle("car", 7, 10),
]


class SaveThemTests(unittest.TestCase):
    def test_plans_feasible_rocket_then_walk_route(self):
        route = plan_route(MAP, VEHICLES)
        self.assertEqual(route.vehicle, "rocket")
        self.assertEqual(route.actions.count("dismount"), 1)
        self.assertEqual(sum(action in {"up", "right", "down", "left"} for action in route.actions), 11)
        self.assertEqual(route.fuel_used, 80)
        self.assertEqual(route.food_used, 83)

    def test_route_reaches_goal_and_walks_on_water_only_after_dismount(self):
        route = plan_route(MAP, VEHICLES)
        row, column = 7, 0
        mode = route.vehicle
        for action in route.actions:
            if action == "dismount":
                mode = "walk"
                continue
            dr, dc = {"up": (-1, 0), "right": (0, 1), "down": (1, 0), "left": (0, -1)}[action]
            row, column = row + dr, column + dc
            if MAP[row][column] == "W":
                self.assertEqual(mode, "walk")
        self.assertEqual((row, column), (4, 8))

    def test_rejects_invalid_map(self):
        with self.assertRaises(SaveThemError):
            validate_grid([["S", "G"]])


if __name__ == "__main__":
    unittest.main()
