from __future__ import annotations

import unittest
from datetime import datetime

from src.windpower import (
    ForecastPoint, TurbineDocumentation, build_schedule, parse_power_deficit,
)


class WindpowerScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = TurbineDocumentation(
            rated_power_kw=14, cutoff_wind_ms=14, minimum_wind_ms=4,
            wind_yields=((4, .10, .15), (6, .30, .40), (8, .60, .70),
                         (10, .90, 1), (12, 1, 1)),
        )

    def test_secures_storms_and_uses_lowest_reliably_productive_wind(self) -> None:
        forecast = [
            ForecastPoint(datetime(2026, 8, 6, 18), 25),
            ForecastPoint(datetime(2026, 8, 6, 20), 5.9),
            ForecastPoint(datetime(2026, 8, 8, 20), 5.9),
            ForecastPoint(datetime(2026, 8, 9, 18), 22),
        ]
        result = build_schedule(forecast, self.docs, 4)
        self.assertEqual(result["2026-08-06 18:00:00"]["pitchAngle"], 90)
        self.assertEqual(result["2026-08-09 18:00:00"]["turbineMode"], "idle")
        self.assertEqual(result["2026-08-06 20:00:00"], {
            "pitchAngle": 0, "turbineMode": "production", "windMs": 5.9,
        })

    def test_parses_upper_bound_of_power_deficit(self) -> None:
        self.assertEqual(parse_power_deficit({"powerDeficitKw": "3-4"}), 4)


if __name__ == "__main__":
    unittest.main()
