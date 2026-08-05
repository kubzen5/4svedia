from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from src.api_client import ApiClient


class ReactorError(RuntimeError):
    """Raised when the reactor API returns an invalid or unsafe state."""


FLAG_PATTERN = re.compile(r"\{FLG:[^}]+}")


def is_success_response(payload: Mapping[str, Any]) -> bool:
    if payload.get("reached_goal") is True:
        return True
    return bool(FLAG_PATTERN.search(str(payload.get("message", ""))))


@dataclass(frozen=True, slots=True)
class ReactorBlock:
    col: int
    top_row: int
    bottom_row: int
    direction: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ReactorBlock":
        try:
            block = cls(
                col=int(payload["col"]),
                top_row=int(payload["top_row"]),
                bottom_row=int(payload["bottom_row"]),
                direction=str(payload["direction"]).lower(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReactorError(f"Invalid reactor block: {payload!r}") from exc
        if block.bottom_row != block.top_row + 1:
            raise ReactorError("A reactor block must occupy exactly two rows")
        if block.direction not in {"up", "down"}:
            raise ReactorError(f"Invalid block direction: {block.direction!r}")
        return block

    def next_rows(self, board_height: int) -> tuple[int, int]:
        """Return rows occupied after the next command advances the block."""

        delta = -1 if self.direction == "up" else 1
        next_top = self.top_row + delta
        if next_top < 1 or next_top + 1 > board_height:
            delta = -delta
            next_top = self.top_row + delta
        return next_top, next_top + 1


@dataclass(frozen=True, slots=True)
class ReactorState:
    player_col: int
    player_row: int
    goal_col: int
    goal_row: int
    width: int
    height: int
    blocks: tuple[ReactorBlock, ...]
    reached_goal: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ReactorState":
        try:
            board = payload["board"]
            player = payload["player"]
            goal = payload["goal"]
            raw_blocks = payload["blocks"]
            if not isinstance(board, Sequence) or isinstance(board, (str, bytes)):
                raise TypeError("board is not a sequence")
            height = len(board)
            width = len(board[0]) if height else 0
            if not height or not width or any(len(row) != width for row in board):
                raise ValueError("board must be a non-empty rectangle")
            if not isinstance(player, Mapping) or not isinstance(goal, Mapping):
                raise TypeError("player and goal must be objects")
            if not isinstance(raw_blocks, Sequence):
                raise TypeError("blocks must be a sequence")
            state = cls(
                player_col=int(player["col"]),
                player_row=int(player["row"]),
                goal_col=int(goal["col"]),
                goal_row=int(goal["row"]),
                width=width,
                height=height,
                blocks=tuple(ReactorBlock.from_payload(item) for item in raw_blocks),
                reached_goal=bool(payload.get("reached_goal", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ReactorError):
                raise
            raise ReactorError("Invalid reactor state returned by API") from exc
        if not (1 <= state.player_col <= width and 1 <= state.player_row <= height):
            raise ReactorError("Player position is outside the board")
        return state

    def safe_after_tick(self, column: int) -> bool:
        if not 1 <= column <= self.width:
            return False
        return all(
            self.player_row not in block.next_rows(self.height)
            for block in self.blocks
            if block.col == column
        )


def choose_command(state: ReactorState) -> str:
    """Choose one safe command, preferring progress towards the goal."""

    if state.reached_goal or state.player_col == state.goal_col:
        raise ReactorError("The robot has already reached the goal")

    direction = 1 if state.goal_col > state.player_col else -1
    forward = state.player_col + direction
    if state.safe_after_tick(forward):
        return "right" if direction == 1 else "left"
    if state.safe_after_tick(state.player_col):
        return "wait"

    retreat = state.player_col - direction
    if state.safe_after_tick(retreat):
        return "left" if direction == 1 else "right"
    raise ReactorError("No safe command is available for the next tick")


class ReactorClient:
    def __init__(self, hub: ApiClient) -> None:
        self.hub = hub

    def command(self, command: str) -> Mapping[str, Any]:
        if command not in {"start", "reset", "left", "wait", "right"}:
            raise ReactorError(f"Unsupported reactor command: {command}")
        response = self.hub.post_json(
            "verify",
            {
                "apikey": self.hub.api_key,
                "task": "reactor",
                "answer": {"command": command},
            },
        )
        if not isinstance(response, Mapping):
            raise ReactorError("Reactor API response must be a JSON object")
        return response

    def solve(self, *, max_steps: int = 100) -> tuple[Mapping[str, Any], list[str]]:
        response = self.command("start")
        commands = ["start"]
        print("reactor command: start")

        for _ in range(max_steps):
            if is_success_response(response):
                return response, commands
            state = ReactorState.from_payload(response)
            command = choose_command(state)
            print(f"reactor command: {command}")
            response = self.command(command)
            commands.append(command)

        raise ReactorError(f"Goal was not reached within {max_steps} commands")
