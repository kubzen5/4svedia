from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.api_client import ApiClient, ApiClientError


TASK_NAME = "okoeditor"
SKOLWIN_RECORD_ID = "380792b2c86d9c5be670b3bde48e187b"
KOMAROWO_INCIDENT_ID = "bcdfc393f811cc05d3a189c679f50659"


@dataclass(frozen=True, slots=True)
class Update:
    page: str
    record_id: str
    title: str | None = None
    content: str | None = None
    done: str | None = None

    def answer(self) -> dict[str, str]:
        result = {"page": self.page, "id": self.record_id, "action": "update"}
        for name in ("title", "content", "done"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        return result


def required_updates() -> tuple[Update, ...]:
    """Return the complete, deterministic edit set required by the mission."""

    return (
        Update(
            page="incydenty",
            record_id=SKOLWIN_RECORD_ID,
            title="MOVE04 Wykryto ruch zwierząt nieopodal miasta Skolwin",
            content=(
                "Czujniki w okolicach Skolwina zarejestrowały ruch zwierząt. "
                "Analiza nagrań wskazuje na bobry przemieszczające się w stronę rzeki; "
                "ślady oraz charakter ruchu potwierdzają tę klasyfikację."
            ),
        ),
        Update(
            page="zadania",
            record_id=SKOLWIN_RECORD_ID,
            content=(
                "Nagrania z okolic Skolwina zostały zbadane. Widziano tam zwierzęta, "
                "najprawdopodobniej bobry poruszające się w stronę rzeki."
            ),
            done="YES",
        ),
        Update(
            page="incydenty",
            record_id=KOMAROWO_INCIDENT_ID,
            title="MOVE01 Wykryto ruch ludzi w okolicach miasta Komarowo",
            content=(
                "Czujniki wykryły ruch ludzi w okolicach niezamieszkałego miasta "
                "Komarowo. Zdarzenie wymaga pilnej obserwacji operatorów."
            ),
        ),
    )


def _verify(hub: ApiClient, answer: Mapping[str, str]) -> Mapping[str, Any]:
    response = hub.post_json(
        "verify", {"apikey": hub.api_key, "task": TASK_NAME, "answer": answer}
    )
    if not isinstance(response, Mapping):
        raise ApiClientError("okoeditor returned a non-object response")
    return response


def apply_updates(
    hub: ApiClient, updates: Sequence[Update] | None = None
) -> list[Mapping[str, Any]]:
    """Apply all edits in order and finish with the verifier's done action."""

    responses = [_verify(hub, update.answer()) for update in updates or required_updates()]
    responses.append(_verify(hub, {"action": "done"}))
    return responses
