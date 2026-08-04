from src.failure import build_condensed_log, estimate_tokens, feedback_terms, parse_events


SAMPLE = """\
[2026-02-26 06:04] [CRIT] ECCS8 runaway outlet temperature. Protection interlock initiated reactor trip.
[2026-02-26 06:11] [WARN] PWR01 input ripple crossed warning limits.
[2026-02-26 07:00] [INFO] USER42 signed in successfully.
2026-02-26 10:15 ERROR [WTANK07] coolant below critical threshold. Hard trip initiated.
"""


def test_parse_and_condense_keeps_plant_events_and_format() -> None:
    result = build_condensed_log(parse_events(SAMPLE))
    assert result.splitlines() == [
        "[2026-02-26 06:04] [CRIT] ECCS8 runaway outlet temperature. Protection interlock initiated reactor trip",
        "[2026-02-26 06:11] [WARN] PWR01 input ripple crossed warning limits",
        "[2026-02-26 10:15] [ERROR] WTANK07 coolant below critical threshold. Hard trip initiated",
    ]


def test_budget_is_hard_and_feedback_extracts_known_component() -> None:
    events = parse_events(SAMPLE)
    result = build_condensed_log(events, token_limit=40)
    assert estimate_tokens(result) <= 40
    assert feedback_terms({"message": "Brakuje WTANK07"}, {"ECCS8", "WTANK07"}) == {"WTANK07"}
