from echo_os.transcript import TurnDigest, is_long_horizon


def digest(seconds, tools):
    return TurnDigest(ask="a", response="r", tool_calls=tools, duration_seconds=seconds)


def test_long_and_busy_turn_passes():
    assert is_long_horizon(digest(200, 6), min_seconds=180, min_tool_calls=5)


def test_short_turn_fails_even_with_many_tools():
    assert not is_long_horizon(digest(60, 40), min_seconds=180, min_tool_calls=5)


def test_long_turn_with_few_tools_fails():
    assert not is_long_horizon(digest(600, 2), min_seconds=180, min_tool_calls=5)


def test_thresholds_are_inclusive():
    assert is_long_horizon(digest(180, 5), min_seconds=180, min_tool_calls=5)
