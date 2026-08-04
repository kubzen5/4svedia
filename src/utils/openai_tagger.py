from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field, ValidationError

AllowedTag = Literal[
    "IT",
    "transport",
    "edukacja",
    "medycyna",
    "praca z ludźmi",
    "praca z pojazdami",
    "praca fizyczna",
]

ALLOWED_TAGS: tuple[str, ...] = (
    "IT",
    "transport",
    "edukacja",
    "medycyna",
    "praca z ludźmi",
    "praca z pojazdami",
    "praca fizyczna",
)


class PersonTags(BaseModel):
    person_id: int
    tags: list[AllowedTag] = Field(default_factory=list)


class TaggingResponse(BaseModel):
    people: list[PersonTags]


class OpenAITaggingError(RuntimeError):
    """Błąd klasyfikacji stanowisk przez model OpenAI."""


@dataclass(frozen=True, slots=True)
class OpenAITaggerConfig:
    api_key: str
    model: str
    batch_size: int = 25
    timeout_seconds: float = 60.0
    max_retries: int = 3

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OPENAI_API_KEY nie może być pusty")
        if not self.model.strip():
            raise ValueError("OPENAI_MODEL nie może być pusty")
        if self.batch_size < 1:
            raise ValueError("batch_size musi być większe od zera")


class OpenAITagger:
    SYSTEM_PROMPT = """
Jesteś klasyfikatorem opisów stanowisk pracy.

Dla każdej osoby przypisz zero, jeden lub wiele tagów wyłącznie z listy:
- IT
- transport
- edukacja
- medycyna
- praca z ludźmi
- praca z pojazdami
- praca fizyczna

Znaczenie tagów:
- IT: programowanie, systemy informatyczne, sieci, dane, wsparcie techniczne.
- transport: logistyka, spedycja, przewóz, dostawy, dystrybucja, planowanie tras,
  transport towarów lub osób, łańcuch dostaw.
- edukacja: nauczanie, szkolenia, szkoła, uczelnia, opieka edukacyjna.
- medycyna: ochrona zdrowia, leczenie, diagnostyka, farmacja, opieka medyczna.
- praca z ludźmi: regularny bezpośredni kontakt z klientami, pacjentami,
  uczniami, pracownikami lub kontrahentami; obsługa, negocjacje albo doradztwo.
- praca z pojazdami: prowadzenie, obsługa, naprawa, serwisowanie lub zarządzanie
  samochodami, ciężarówkami albo innymi pojazdami.
- praca fizyczna: dominująca praca manualna, załadunek, rozładunek, produkcja,
  budowa, naprawy lub ręczne prace magazynowe.

Zasady:
1. Klasyfikuj wyłącznie na podstawie opisu pola job.
2. Nie zgaduj. Dodaj tag tylko wtedy, gdy opis wskazuje na niego wprost lub
   bardzo wyraźnie.
3. Zwróć dokładnie jeden wynik dla każdego person_id.
4. Nie zmieniaj person_id.
5. Nie dodawaj komentarzy ani tagów spoza listy.
""".strip()

    def __init__(self, config: OpenAITaggerConfig) -> None:
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    def add_tags(
        self,
        dataframe: pd.DataFrame,
        *,
        job_column: str = "job",
        id_column: str = "person_id",
    ) -> pd.DataFrame:
        """Zwraca kopię DataFrame z kolumną ``tags`` typu list[str]."""
        missing = {job_column, id_column} - set(dataframe.columns)
        if missing:
            raise ValueError(
                f"Brak wymaganych kolumn: {', '.join(sorted(missing))}"
            )

        result_df = dataframe.copy()
        if result_df.empty:
            result_df["tags"] = pd.Series(dtype=object)
            return result_df

        all_tags_by_id: dict[int, list[str]] = {}

        for start in range(0, len(result_df), self.config.batch_size):
            batch = result_df.iloc[start : start + self.config.batch_size]
            tags_by_id = self._tag_batch(
                batch,
                job_column=job_column,
                id_column=id_column,
            )

            duplicated_ids = set(all_tags_by_id).intersection(tags_by_id)
            if duplicated_ids:
                raise OpenAITaggingError(
                    f"Model zwrócił zduplikowane identyfikatory: {duplicated_ids}"
                )

            all_tags_by_id.update(tags_by_id)

        expected_ids = {int(value) for value in result_df[id_column].tolist()}
        returned_ids = set(all_tags_by_id)

        if expected_ids != returned_ids:
            missing_ids = sorted(expected_ids - returned_ids)
            unexpected_ids = sorted(returned_ids - expected_ids)
            raise OpenAITaggingError(
                "Niepełna odpowiedź modelu. "
                f"Brakujące ID: {missing_ids}; nieoczekiwane ID: {unexpected_ids}"
            )

        result_df["tags"] = result_df[id_column].map(
            lambda value: all_tags_by_id[int(value)]
        )
        return result_df

    def _tag_batch(
        self,
        batch: pd.DataFrame,
        *,
        job_column: str,
        id_column: str,
    ) -> dict[int, list[str]]:
        people = [
            {
                "person_id": int(row[id_column]),
                "job": "" if pd.isna(row[job_column]) else str(row[job_column]),
            }
            for _, row in batch.iterrows()
        ]
        expected_ids = {person["person_id"] for person in people}

        try:
            response = self.client.responses.parse(
                model=self.config.model,
                input=[
                    {
                        "role": "developer",
                        "content": self.SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"people": people},
                            ensure_ascii=False,
                        ),
                    },
                ],
                text_format=TaggingResponse,
                store=False,
            )
        except (OpenAIError, ValidationError) as exc:
            raise OpenAITaggingError(
                f"Nie udało się sklasyfikować opisów stanowisk: {exc}"
            ) from exc

        parsed = response.output_parsed
        if parsed is None:
            refusal = getattr(response, "refusal", None)
            raise OpenAITaggingError(
                f"Model nie zwrócił danych strukturalnych. Refusal: {refusal!r}"
            )

        tags_by_id: dict[int, list[str]] = {}
        for item in parsed.people:
            if item.person_id not in expected_ids:
                raise OpenAITaggingError(
                    f"Model zwrócił nieznane person_id={item.person_id}"
                )
            if item.person_id in tags_by_id:
                raise OpenAITaggingError(
                    f"Model zwrócił person_id={item.person_id} więcej niż raz"
                )

            # Usunięcie duplikatów przy zachowaniu ustalonej kolejności tagów.
            tags_by_id[item.person_id] = [
                tag for tag in ALLOWED_TAGS if tag in item.tags
            ]

        if set(tags_by_id) != expected_ids:
            missing_ids = sorted(expected_ids - set(tags_by_id))
            raise OpenAITaggingError(
                f"Model pominął osoby z ID: {missing_ids}"
            )

        return tags_by_id
