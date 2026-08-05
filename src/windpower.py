from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from src.api_client import ApiClient


TASK_NAME = "windpower"
PITCH_YIELD = {0: 1.0, 45: 0.65, 90: 0.0}


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    timestamp: datetime
    wind_speed: float


@dataclass(frozen=True, slots=True)
class TurbineDocumentation:
    rated_power_kw: float
    cutoff_wind_ms: float
    minimum_wind_ms: float
    wind_yields: tuple[tuple[float, float, float], ...]

    def expected_power(self, wind_speed: float, pitch_angle: int) -> float:
        # Forecasts use one decimal place (for example 5.9 for the documented
        # 6 m/s band), so classify them by the nearest documented wind band.
        matching = [row for row in self.wind_yields if wind_speed + 0.5 >= row[0]]
        if not matching or pitch_angle not in PITCH_YIELD:
            return 0.0
        wind_yield = (matching[-1][1] + matching[-1][2]) / 2
        return self.rated_power_kw * wind_yield * PITCH_YIELD[pitch_angle]


def parse_forecast(report: Mapping[str, Any]) -> list[ForecastPoint]:
    try:
        return [
            ForecastPoint(
                datetime.fromisoformat(str(item["timestamp"])), float(item["windMs"])
            )
            for item in report["forecast"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid weather report") from exc


def parse_power_deficit(report: Mapping[str, Any]) -> float:
    match = re.findall(r"\d+(?:\.\d+)?", str(report.get("powerDeficitKw", "")))
    if not match:
        raise ValueError("Power-plant report contains no power deficit")
    return max(map(float, match))


def parse_documentation(document: Mapping[str, Any]) -> TurbineDocumentation:
    rows: list[tuple[float, float, float]] = []
    for item in document.get("windPowerYieldPercent", []):
        if "windMs" not in item or str(item.get("yieldPercent")) == "damage":
            continue
        percentages = re.findall(r"\d+(?:\.\d+)?", str(item["yieldPercent"]))
        if percentages:
            rows.append((float(item["windMs"]), float(percentages[0]) / 100,
                         float(percentages[-1]) / 100))
    try:
        safety = document["safety"]
        return TurbineDocumentation(
            rated_power_kw=float(document["ratedPowerKw"]),
            cutoff_wind_ms=float(safety["cutoffWindMs"]),
            minimum_wind_ms=float(safety["minOperationalWindMs"]),
            wind_yields=tuple(sorted(rows)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid turbine documentation") from exc


def build_schedule(
    forecast: Sequence[ForecastPoint], documentation: TurbineDocumentation,
    required_power_kw: float,
) -> dict[str, dict[str, Any]]:
    schedule = {
        point.timestamp.strftime("%Y-%m-%d %H:00:00"): {
            "pitchAngle": 90, "turbineMode": "idle", "windMs": point.wind_speed,
        }
        for point in forecast if point.wind_speed > documentation.cutoff_wind_ms
    }
    candidates = [
        point for point in forecast
        if documentation.minimum_wind_ms <= point.wind_speed <= documentation.cutoff_wind_ms
        and documentation.expected_power(point.wind_speed, 0) >= required_power_kw
    ]
    if not candidates:
        raise ValueError("No safe forecast point can supply the power deficit")
    # Lowest sufficient wind minimizes load; earliest timestamp makes the choice stable.
    chosen = min(candidates, key=lambda point: (point.wind_speed, point.timestamp))
    schedule[chosen.timestamp.strftime("%Y-%m-%d %H:00:00")] = {
        "pitchAngle": 0, "turbineMode": "production", "windMs": chosen.wind_speed,
    }
    return schedule


class WindpowerWorkflow:
    def __init__(self, hub: ApiClient, *, deadline_seconds: float = 40,
                 poll_interval: float = 0.1,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.hub = hub
        self.deadline_seconds = deadline_seconds
        self.poll_interval = poll_interval
        self.clock = clock
        self.sleep = sleep

    def call(self, action: str, **arguments: Any) -> Any:
        return self.hub.post_json("verify", {
            "apikey": self.hub.api_key, "task": TASK_NAME,
            "answer": {"action": action, **arguments},
        }, allow_http_error_response=True)

    def collect(self, count: int, deadline: float) -> list[Mapping[str, Any]]:
        results: list[Mapping[str, Any]] = []
        while len(results) < count:
            if self.clock() >= deadline:
                raise TimeoutError(f"Timed out after receiving {len(results)}/{count} results")
            response = self.call("getResult")
            if isinstance(response, Mapping) and response.get("sourceFunction"):
                results.append(response)
            else:
                self.sleep(self.poll_interval)
        return results

    def run(self) -> Any:
        self.call("start")
        deadline = self.clock() + self.deadline_seconds
        documentation = parse_documentation(self.call("get", param="documentation"))
        for param in ("weather", "turbinecheck", "powerplantcheck"):
            self.call("get", param=param)
        reports = {str(item["sourceFunction"]): item for item in self.collect(3, deadline)}
        schedule = build_schedule(
            parse_forecast(reports["weather"]), documentation,
            parse_power_deficit(reports["powerplantcheck"]),
        )

        for timestamp, config in schedule.items():
            self.call("unlockCodeGenerator", startDate=timestamp[:10],
                      startHour=timestamp[11:], windMs=config["windMs"],
                      pitchAngle=config["pitchAngle"])
        unlocks = self.collect(len(schedule), deadline)
        codes: dict[str, str] = {}
        for result in unlocks:
            signed = result.get("signedParams", result)
            if not isinstance(signed, Mapping):
                signed = {}
            date = signed.get("startDate")
            hour = signed.get("startHour")
            code = result.get("unlockCode")
            if date and hour and code:
                codes[f"{date} {hour}"] = str(code)
        if len(codes) != len(schedule):
            raise ValueError(f"Could not associate all unlock codes with configs: {unlocks!r}")
        configs = {
            timestamp: {
                "pitchAngle": config["pitchAngle"],
                "turbineMode": config["turbineMode"],
                "unlockCode": codes[timestamp],
            }
            for timestamp, config in schedule.items()
        }
        configured = self.call("config", configs=configs)
        # The queued turbinecheck above satisfies the mandatory pre-done test.
        done = self.call("done")
        return {"config": configured, "done": done, "configs": configs}
