import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.api_client import ApiClient, ApiConfig
from src.utils.openai_tagger import OpenAITagger, OpenAITaggerConfig


REFERENCE_DATE = pd.Timestamp("2026-08-03")
OUTPUT_DATA_RAW_PATH = Path("data_raw/s01e01/people.csv")
OUTPUT_FILTERED_PATH = Path("data/s01e01/transport_people.csv")


def calculate_age(birth_dates: pd.Series) -> pd.Series:
    birthday_already_passed = (
        (birth_dates.dt.month < REFERENCE_DATE.month)
        | (
            (birth_dates.dt.month == REFERENCE_DATE.month)
            & (birth_dates.dt.day <= REFERENCE_DATE.day)
        )
    )

    return (
        REFERENCE_DATE.year
        - birth_dates.dt.year
        - (~birthday_already_passed).astype(int)
    )


def select_candidates(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Wybierz osoby spełniające warunki niezwiązane z wykonywaną pracą."""
    candidates = dataframe.copy()
    candidates["birthDate"] = pd.to_datetime(
        candidates["birthDate"],
        format="%Y-%m-%d",
        errors="coerce",
    )
    candidates["age"] = calculate_age(candidates["birthDate"])

    demographic_filter = (
        candidates["gender"].eq("M")
        & candidates["age"].between(20, 40, inclusive="both")
        & candidates["birthPlace"]
        .fillna("")
        .str.strip()
        .str.casefold()
        .eq("grudziądz".casefold())
    )

    # Oryginalny indeks jest stabilnym identyfikatorem potrzebnym taggerowi.
    return (
        candidates.loc[demographic_filter]
        .reset_index(names="person_id")
    )


def build_answer(dataframe: pd.DataFrame) -> list[dict[str, object]]:
    answer: list[dict[str, object]] = []

    for _, row in dataframe.iterrows():
        answer.append(
            {
                "name": str(row["name"]),
                "surname": str(row["surname"]),
                "gender": str(row["gender"]),
                "born": int(row["birthDate"].year),
                "city": str(row["birthPlace"]),
                "tags": list(row["tags"]),
            }
        )

    return answer


def main() -> None:
    load_dotenv(override=True)

    agenthub_client = ApiClient(
        ApiConfig(
            api_url=os.getenv("AGENTHUB_API_URL"),
            api_key=os.getenv("AGENTHUB_API_KEY"),
        )
    )
    tagger = OpenAITagger(
        OpenAITaggerConfig(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", ""),
        )
    )

    agenthub_client.download(
        f"data/{agenthub_client.api_key}/people.csv",
        OUTPUT_DATA_RAW_PATH,
        headers={"Accept": "text/csv"},
    )

    people = pd.read_csv(OUTPUT_DATA_RAW_PATH)
    candidates = select_candidates(people)

    # Każda potencjalna osoba otrzymuje komplet pasujących tagów z OpenAI.
    tagged_candidates = tagger.add_tags(candidates)
    transport_people = (
        tagged_candidates.loc[
            tagged_candidates["tags"].map(lambda tags: "transport" in tags)
        ]
        .sort_values(["surname", "name"])
        .reset_index(drop=True)
    )

    OUTPUT_FILTERED_PATH.parent.mkdir(parents=True, exist_ok=True)
    transport_people.to_csv(OUTPUT_FILTERED_PATH, index=False)

    payload = {
        "apikey": agenthub_client.api_key,
        "task": "people",
        "answer": build_answer(transport_people),
    }
    verification = agenthub_client.post_json("verify", payload)
    print(verification)


if __name__ == "__main__":
    main()
