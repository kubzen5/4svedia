import unittest

from src.reactor import ReactorBlock, ReactorState, choose_command, is_success_response


def state(*blocks: ReactorBlock, player_col: int = 2) -> ReactorState:
    return ReactorState(
        player_col=player_col,
        player_row=5,
        goal_col=7,
        goal_row=5,
        width=7,
        height=5,
        blocks=blocks,
    )


class ReactorTests(unittest.TestCase):
    def test_recognizes_board_and_flag_success_responses(self) -> None:
        self.assertTrue(is_success_response({"reached_goal": True}))
        self.assertTrue(is_success_response({"message": "Success {FLG:demo}"}))
        self.assertFalse(is_success_response({"message": "Player moved right."}))

    def test_block_predicts_motion_and_reverses_at_extremes(self) -> None:
        self.assertEqual(ReactorBlock(2, 2, 3, "down").next_rows(5), (3, 4))
        self.assertEqual(ReactorBlock(2, 4, 5, "down").next_rows(5), (3, 4))
        self.assertEqual(ReactorBlock(2, 1, 2, "up").next_rows(5), (2, 3))

    def test_moves_right_when_next_column_will_be_clear(self) -> None:
        self.assertEqual(
            choose_command(state(ReactorBlock(3, 4, 5, "up"))), "right"
        )

    def test_waits_when_forward_is_dangerous_but_current_is_safe(self) -> None:
        self.assertEqual(
            choose_command(state(ReactorBlock(3, 3, 4, "down"))), "wait"
        )

    def test_retreats_when_forward_and_current_will_be_dangerous(self) -> None:
        self.assertEqual(
            choose_command(
                state(
                    ReactorBlock(2, 3, 4, "down"),
                    ReactorBlock(3, 3, 4, "down"),
                )
            ),
            "left",
        )

    def test_parses_real_api_shape(self) -> None:
        payload = {
            "board": [["."] * 7 for _ in range(5)],
            "player": {"col": 1, "row": 5},
            "goal": {"col": 7, "row": 5},
            "blocks": [
                {"col": 2, "top_row": 1, "bottom_row": 2, "direction": "down"}
            ],
            "reached_goal": False,
        }
        parsed = ReactorState.from_payload(payload)
        self.assertEqual(parsed.width, 7)
        self.assertEqual(parsed.blocks[0].direction, "down")


if __name__ == "__main__":
    unittest.main()
