from conftest import T0, assistant_text, human, tool_result, tool_use, turn_end

from echo_os.transcript import read_last_turn


def test_digest_covers_only_the_turn_after_the_previous_turn_end(write_transcript):
    path = write_transcript([
        human("old ask", 0), tool_use("Bash", 5), tool_result(6), assistant_text("old answer", 10),
        turn_end(11),
        human("Refactor billing", 100), tool_use("Read", 110), tool_result(111),
        tool_use("Edit", 200), tool_result(201), assistant_text("Done. Tests pass.", 400),
    ])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 405)
    assert digest.ask == "Refactor billing"
    assert digest.response == "Done. Tests pass."
    assert digest.tool_calls == 2
    assert digest.duration_seconds == 305


def test_response_is_text_after_the_last_tool_call(write_transcript):
    path = write_transcript([
        human("go", 0), assistant_text("Let me look.", 1), tool_use("Read", 2), tool_result(3),
        assistant_text("Fixed it.", 4), assistant_text("All green.", 5),
    ])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 6)
    assert digest.response == "Fixed it.\n\nAll green."


def test_sidechain_tool_calls_are_not_counted(write_transcript):
    path = write_transcript([human("go", 0), tool_use("Agent", 1), tool_use("Read", 2, sidechain=True),
                             tool_result(3), assistant_text("ok", 4)])
    assert read_last_turn(path, ended_at=T0.timestamp() + 5).tool_calls == 1


def test_tool_results_and_meta_entries_do_not_start_a_turn(write_transcript):
    path = write_transcript([
        human("real ask", 0), tool_use("Bash", 1), tool_result(2),
        human("<system-reminder>x</system-reminder>", 3, isMeta=True),
        assistant_text("done", 4),
    ])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 5)
    assert digest.ask == "real ask"
    assert digest.duration_seconds == 5


def test_follow_up_typed_mid_turn_keeps_the_original_start(write_transcript):
    path = write_transcript([human("first", 0), tool_use("Bash", 50), tool_result(51),
                             human("also do X", 60), assistant_text("done both", 300)])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 300)
    assert digest.ask == "first\n\nalso do X"
    assert digest.duration_seconds == 300


def test_last_assistant_message_from_the_hook_overrides_a_stale_transcript(write_transcript):
    path = write_transcript([human("go", 0), tool_use("Bash", 1), tool_result(2)])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 3, last_assistant_message="Hook text")
    assert digest.response == "Hook text"


def test_list_content_text_blocks_count_as_a_human_prompt(write_transcript):
    entry = human("", 0)
    entry["message"]["content"] = [{"type": "text", "text": "from a list"}]
    path = write_transcript([entry, assistant_text("ok", 1)])
    assert read_last_turn(path, ended_at=T0.timestamp() + 1).ask == "from a list"


def test_corrupt_lines_are_skipped(write_transcript):
    path = write_transcript([human("go", 0), "{not json", assistant_text("ok", 1)])
    assert read_last_turn(path, ended_at=T0.timestamp() + 1).response == "ok"


def test_missing_transcript_returns_none(tmp_path):
    assert read_last_turn(tmp_path / "nope.jsonl", ended_at=0) is None


def test_transcript_without_a_human_prompt_returns_none(write_transcript):
    path = write_transcript([assistant_text("hello", 0)])
    assert read_last_turn(path, ended_at=T0.timestamp()) is None
