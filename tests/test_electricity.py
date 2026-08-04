from src.electricity import DELTAS, OPPOSITE, Tile, rotate, solve_board, solve_codes


def test_rotate_clockwise() -> None:
    assert rotate({"N", "E"}, 1) == {"E", "S"}


def test_solver_finds_closed_connected_grid() -> None:
    solved = [
        {"E", "S"}, {"E", "W"}, {"S", "W"},
        {"N", "S"}, {"E", "S"}, {"N", "S", "W"},
        {"N", "E"}, {"N", "E", "W"}, {"N", "W"},
    ]
    initial = [rotate(edges, (4 - index % 4) % 4) for index, edges in enumerate(solved)]
    tiles = [Tile(index // 3, index % 3, edges) for index, edges in enumerate(initial)]
    rotations = solve_board(tiles)
    result = {
        (tile.row, tile.column): rotate(tile.connectors, rotations[tile.address])
        for tile in tiles
    }
    for position, connectors in result.items():
        for direction in connectors:
            dr, dc = DELTAS[direction]
            assert OPPOSITE[direction] in result[(position[0] + dr, position[1] + dc)]


def test_code_solver_handles_initial_and_partial_board() -> None:
    initial = ((3, 2, 1), (4, 5, 5), (8, 7, 0))
    assert solve_codes(initial) == {
        "1x1": 0, "1x2": 1, "1x3": 1,
        "2x1": 1, "2x2": 3, "2x3": 0,
        "3x1": 1, "3x2": 0, "3x3": 0,
    }
