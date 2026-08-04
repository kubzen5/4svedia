from src.drone import mission_instructions


def test_mission_instructions_use_one_based_sector_and_required_target() -> None:
    instructions = mission_instructions(3, 4)
    assert "setDestinationObject(PWR6132PL)" in instructions
    assert "set(3,4)" in instructions
    assert "set(return)" in instructions
    assert instructions.index("set(return)") < instructions.index("flyToLocation")
    assert instructions[-1] == "flyToLocation"


def test_mission_instructions_reject_invalid_sector() -> None:
    try:
        mission_instructions(0, 1)
    except ValueError as exc:
        assert "one-based" in str(exc)
    else:
        raise AssertionError("invalid sector should fail")
