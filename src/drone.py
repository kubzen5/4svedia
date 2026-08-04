from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError

from src.api_client import ApiClient


POWER_PLANT_ID = "PWR6132PL"


class DamSector(BaseModel):
    """One-based location of the dam on a gridded map."""

    column: int = Field(ge=1)
    row: int = Field(ge=1)
    grid_columns: int = Field(ge=1)
    grid_rows: int = Field(ge=1)
    explanation: str


class DroneMapAnalyzerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DroneMapAnalyzerConfig:
    api_key: str
    model: str
    timeout_seconds: float = 90.0


class DroneMapAnalyzer:
    def __init__(self, config: DroneMapAnalyzerConfig) -> None:
        if not config.api_key.strip() or not config.model.strip():
            raise ValueError("OpenAI API key and model cannot be empty")
        self.client = OpenAI(api_key=config.api_key, timeout=config.timeout_seconds)
        self.model = config.model

    def locate_dam(self, image_data_url: str) -> DamSector:
        """Count the grid and return the one-based sector containing the dam."""
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Analyze this fictional game map carefully. Count every grid "
                                "column and row. Locate the dam next to the deliberately brighter "
                                "water. Coordinates are one-based from the top-left: x is column "
                                "and y is row. Return the dam's sector, total grid dimensions, "
                                "and a short visual justification. Do not guess from landmarks."
                            ),
                        },
                        {"type": "input_image", "image_url": image_data_url, "detail": "high"},
                    ],
                }],
                text_format=DamSector,
                store=False,
            )
        except (OpenAIError, ValidationError) as exc:
            raise DroneMapAnalyzerError(f"Map analysis failed: {exc}") from exc
        sector = response.output_parsed
        if sector is None:
            raise DroneMapAnalyzerError("Vision model returned no structured map analysis")
        if sector.column > sector.grid_columns or sector.row > sector.grid_rows:
            raise DroneMapAnalyzerError("Vision model returned a sector outside the grid")
        return sector


def mission_instructions(column: int, row: int) -> list[str]:
    """Build the smallest complete mission accepted by the DRN-BMB7 simulator."""
    if column < 1 or row < 1:
        raise ValueError("Drone sector coordinates are one-based positive integers")
    return [
        "hardReset",
        f"setDestinationObject({POWER_PLANT_ID})",
        f"set({column},{row})",
        "set(20m)",
        "set(engineON)",
        "set(100%)",
        "set(destroy)",
        "set(return)",
        "flyToLocation",
    ]


class DroneClient:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def fetch_map_data_url(self) -> str:
        """Fetch the protected map without exposing the Hub key to vision."""
        payload = self.client.request_bytes(f"data/{self.client.api_key}/drone.png")
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def submit(self, instructions: list[str]) -> Any:
        if not instructions:
            raise ValueError("At least one drone instruction is required")
        return self.client.post_json(
            "verify",
            {
                "apikey": self.client.api_key,
                "task": "drone",
                "answer": {"instructions": instructions},
            },
            allow_http_error_response=True,
        )

    def solve(self, analyzer: DroneMapAnalyzer) -> tuple[DamSector, Any]:
        sector = analyzer.locate_dam(self.fetch_map_data_url())
        response = self.submit(mission_instructions(sector.column, sector.row))
        return sector, response
