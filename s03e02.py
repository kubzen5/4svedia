from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.firmware import FirmwareClient, FirmwareError, find_confirmation


MAX_STEPS = 30
BINARY_FILE_MESSAGE = "(BINARY FILE TOO LARGE TO BE OPENED)"
RESTRICTED_COOLER_PATHS = (
    "/opt/firmware/cooler/.env",
    "/opt/firmware/cooler/.git",
    "/opt/firmware/cooler/logs",
    "/opt/firmware/cooler/storage.cfg",
)
SEND_COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "send_command",
        "description": (
            "Run exactly one command in a virtual filesystem. Supported commands: "
            "help, ls [path], cat <path>, cd [path], pwd, rm <file>, "
            "editline <file> <line-number> <content>, date, uptime, "
            "find <filename-pattern>, history, whoami. This is not a Unix shell: "
            "do not use flags, pipes, redirections, semicolons, &&, or Unix tools. "
            "Never call reboot: it discards all changes and restores the broken state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}

SYSTEM_PROMPT = """You are solving a remote firmware investigation task.
Use send_command to inspect the environment and determine how to repair the cooler
firmware. Work independently until the operation returns an ECCS confirmation code.
The firmware is under /opt/firmware/cooler. Never inspect /etc, /root, or /proc.
This is a small virtual filesystem API, NOT a Unix shell. Issue exactly one supported
command per tool call and use only the syntax stated in the tool description. Never
use shell flags, pipes, redirects, semicolons, &&, or utilities such as head, strings,
stat, checksum tools, or disassemblers. Always examine the complete JSON response:
use its data field, not only its message. Start by listing the relevant directories.
Do not try to print cooler.bin: the client will report that it is too large. Inspect
settings.ini, but never access .env, .git, storage.cfg, or logs: doing so triggers a
20-second security ban. Focus on the configuration and lock file. A safe cooler needs
an active SAFETY_CHECK, test mode disabled, cooling enabled, and no blocked lock file.
Use editline for the necessary settings and remove the lock. NEVER call reboot: it
rebuilds the virtual filesystem from disk, undoing the repair and recreating the lock.
After editing, verify settings.ini and the directory listing, then use uptime or other
safe status checks while waiting for the repaired cooler to emit an ECCS code.
Potentially modifying commands editline and rm are allowed when required.
When finished, return the exact ECCS confirmation code in your final answer.
"""


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def _is_full_binary_cat(command: str) -> bool:
    """Match the guard from the reference loop without blocking focused reads."""

    normalized = command.strip()
    return normalized.startswith("cat") and normalized.endswith("cooler.bin")


def _restricted_path(command: str) -> str | None:
    """Stop known honeypot paths locally so they cannot trigger a remote ban."""

    normalized = command.strip().rstrip("/")
    for path in RESTRICTED_COOLER_PATHS:
        if normalized == path or normalized.endswith(f" {path}"):
            return path
        if f" {path}/" in f" {normalized}/":
            return path
    return None


def _is_reboot(command: str) -> bool:
    return command.strip().lower() == "reboot"


def _tool_response(response: Any) -> str:
    """Preserve the API's data field; it contains listings and file contents."""

    if isinstance(response, str):
        return response
    return json.dumps(response, ensure_ascii=False, indent=2, default=str)


def run_agent(
    openai_client: Any,
    firmware: FirmwareClient,
    model: str,
    *,
    max_steps: int = MAX_STEPS,
) -> tuple[str, list[str]]:
    """Run the chat-completions tool loop and return its final text and models."""

    messages: list[Any] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Investigate and repair the cooler firmware."},
    ]
    model_history: list[str] = []

    for _ in range(max_steps):
        completion = openai_client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[SEND_COMMAND_TOOL],
            tool_choice="auto",
        )
        if getattr(completion, "model", None):
            model_history.append(completion.model)

        message = completion.choices[0].message
        messages.append(message)
        tool_calls = message.tool_calls or []
        if not tool_calls:
            return message.content or "", model_history

        for tool_call in tool_calls:
            tool_result = ""
            if tool_call.function.name == "send_command":
                try:
                    arguments = json.loads(tool_call.function.arguments)
                    command = arguments["command"]
                    if not isinstance(command, str):
                        raise ValueError("command must be a string")
                    print(f"send_command {command}")
                    restricted_path = _restricted_path(command)
                    if restricted_path is not None:
                        tool_result = (
                            f"BLOCKED LOCALLY: {restricted_path} is a known security "
                            "honeypot. Do not retry it or any path below it. Continue "
                            "using settings.ini and cooler-is-blocked.lock."
                        )
                    elif _is_reboot(command):
                        tool_result = (
                            "BLOCKED LOCALLY: reboot restores the original broken "
                            "filesystem, undoing settings.ini edits and recreating "
                            "the lock. Keep the repaired state and check status."
                        )
                    elif _is_full_binary_cat(command):
                        tool_result = BINARY_FILE_MESSAGE
                    else:
                        tool_result = _tool_response(firmware.shell(command).response)
                except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
                    tool_result = f"Invalid send_command arguments: {exc}"
                except FirmwareError as exc:
                    tool_result = f"Command failed: {exc}"
            else:
                tool_result = f"Unknown tool: {tool_call.function.name}"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )
            print(tool_result)

    raise FirmwareError(f"Agent did not finish within {max_steps} steps")


def main() -> None:
    load_dotenv(override=True)
    hub = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
            timeout_seconds=60,
        )
    )
    firmware = FirmwareClient(hub)
    result, model_history = run_agent(
        OpenAI(api_key=required_environment("OPENAI_API_KEY")),
        firmware,
        required_environment("OPENAI_MODEL"),
    )
    print(result)
    print(f"Models used: {', '.join(model_history)}")

    confirmation = find_confirmation(result)
    if confirmation is None:
        raise FirmwareError("The agent finished without an ECCS confirmation code")
    print(json.dumps(firmware.verify(confirmation), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, FirmwareError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"firmware failed: {exc}") from exc
