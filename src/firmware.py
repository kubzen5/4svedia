from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.api_client import ApiClient, ApiClientError


CONFIRMATION_PATTERN = re.compile(r"ECCS-[0-9A-Za-z]{40}")
FORBIDDEN_PATHS = ("/etc", "/root", "/proc")


class FirmwareError(RuntimeError):
    """Raised when the remote firmware workflow cannot safely continue."""


def find_confirmation(value: Any) -> str | None:
    match = CONFIRMATION_PATTERN.search(str(value))
    return match.group(0) if match else None


def validate_command(command: str) -> None:
    """Reject commands which could inspect paths forbidden by the task."""

    normalized = command.strip()
    if not normalized:
        raise FirmwareError("Remote command cannot be empty")
    for path in FORBIDDEN_PATHS:
        if re.search(rf"(?<![\w.-]){re.escape(path)}(?:/|\b)", normalized):
            raise FirmwareError(f"Refusing command targeting forbidden path {path}")


@dataclass(frozen=True, slots=True)
class ShellResult:
    command: str
    response: Any


class FirmwareClient:
    def __init__(
        self,
        hub: ApiClient,
        *,
        max_attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.hub = hub
        self.max_attempts = max_attempts
        self.sleep = sleep

    def shell(self, command: str) -> ShellResult:
        validate_command(command)
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.hub.post_json(
                    "api/shell", {"apikey": self.hub.api_key, "cmd": command}
                )
                return ShellResult(command, response)
            except ApiClientError as exc:
                retryable = "HTTP 429" in str(exc) or "HTTP 503" in str(exc)
                if not retryable or attempt == self.max_attempts:
                    raise FirmwareError(f"Shell command failed: {exc}") from exc
                self.sleep(min(60.0, 2 ** (attempt - 1)))
        raise AssertionError("unreachable")

    def verify(self, confirmation: str) -> Any:
        if find_confirmation(confirmation) != confirmation:
            raise FirmwareError("Invalid firmware confirmation format")
        return self.hub.post_json(
            "verify",
            {
                "apikey": self.hub.api_key,
                "task": "firmware",
                "answer": {"confirmation": confirmation},
            },
        )


def response_text(response: Any) -> str:
    if isinstance(response, Mapping):
        for key in ("output", "stdout", "result", "message", "error"):
            value = response.get(key)
            if isinstance(value, str):
                return value
    return str(response)
