from conftest import T0, assistant_text, human, task_notification, tool_result, tool_use, turn_end

from echo_os.transcript import BackgroundTask, parse_task_notification, read_last_turn


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


def test_the_current_turns_own_end_markers_are_ignored(write_transcript):
    """Claude Code writes stop_hook_summary/turn_duration for the turn right after the Stop hooks run,
    so by the time the transcript is read they're already there."""
    path = write_transcript([
        human("old", 0), assistant_text("old answer", 5), turn_end(6),
        human("What is the webhook secret?", 100), tool_use("Read", 101), tool_result(102),
        assistant_text("It's in Vault.", 112),
        {"type": "system", "subtype": "stop_hook_summary", "timestamp": "2026-10-16T12:01:52Z"},
        turn_end(112.3),
        {"type": "last-prompt"},
    ])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 112)
    assert digest is not None
    assert digest.ask == "What is the webhook secret?"
    assert digest.response == "It's in Vault."
    assert digest.tool_calls == 1


def test_messages_sent_mid_turn_are_part_of_the_ask(write_transcript):
    queued = {"type": "attachment", "isSidechain": False, "timestamp": "2026-10-16T12:00:30Z",
              "attachment": {"type": "queued_command", "prompt": "Also add a popup", "origin": {"kind": "human"}}}
    path = write_transcript([human("Measure latency", 0), tool_use("Bash", 10), tool_result(11), queued,
                             tool_use("Edit", 40), tool_result(41), assistant_text("Done both.", 300)])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 300)
    assert digest.ask == "Measure latency\n\nAlso add a popup"
    assert digest.duration_seconds == 300


def test_a_turn_started_by_a_finished_background_task_has_no_human_ask(write_transcript):
    path = write_transcript([
        human("Run the suite in the background", 0), assistant_text("Running; I'll report back.", 5), turn_end(6),
        task_notification('Background command "Run full typecheck and test suite" completed (exit code 0)', 900),
        assistant_text("All 249 tests pass.", 905),
    ])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 906)
    assert digest.ask == ""
    assert digest.background_tasks == (BackgroundTask("Run full typecheck and test suite", "completed"),)
    assert digest.response == "All 249 tests pass."
    assert digest.duration_seconds == 6


def test_turns_started_by_a_human_have_no_background_tasks(write_transcript):
    path = write_transcript([human("go", 0), assistant_text("done", 5)])
    assert read_last_turn(path, ended_at=T0.timestamp() + 6).background_tasks == ()


def test_tasks_that_finish_together_are_all_listed(write_transcript):
    path = write_transcript([
        turn_end(0),
        task_notification('Agent "Profile from meetings" finished', 10),
        task_notification('Agent "Profile from docs" finished', 10),
        assistant_text("All three helper agents have finished.", 15),
    ])
    digest = read_last_turn(path, ended_at=T0.timestamp() + 16)
    assert [task.label for task in digest.background_tasks] == ["Profile from meetings", "Profile from docs"]


def test_failed_and_nonzero_exit_tasks_are_not_ok():
    assert parse_task_notification(
        '<task-notification><status>completed</status><summary>Background command "npm test" completed '
        '(exit code 1)</summary></task-notification>') == BackgroundTask("npm test", "failed")
    failed = parse_task_notification(
        '<task-notification><status>failed</status><summary>Agent "Deep dive" failed: API error</summary>'
        '</task-notification>')
    assert failed == BackgroundTask("Deep dive", "failed") and not failed.ok


def test_task_labels_are_unescaped_and_fall_back_to_the_summary():
    assert parse_task_notification(
        '<task-notification><status>completed</status><summary>Background command " cd app &amp;&amp; npm run ship" '
        'completed (exit code 0)</summary></task-notification>').label == "cd app && npm run ship"
    assert parse_task_notification(
        "<task-notification><status>killed</status><summary>Something else</summary></task-notification>"
    ) == BackgroundTask("Something else", "killed")


def test_text_that_is_not_a_task_notification_is_ignored():
    assert parse_task_notification("hello") is None
