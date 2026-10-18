from echo_os.echo.kb_usage import KbUsage, kb_usage_from_record


def test_no_kb_record_means_the_agent_was_off():
    assert kb_usage_from_record(None) == KbUsage("off")


def test_relevant_context_is_used_with_its_note_count():
    assert kb_usage_from_record({"relevant": True, "sources": ["a", "b"], "error": None}) == KbUsage("used", notes=2)


def test_searched_but_nothing_relevant():
    assert kb_usage_from_record({"relevant": False, "sources": [], "error": None}) == KbUsage("not-relevant")


def test_logged_out_server_reads_as_needs_login():
    record = {"relevant": False, "sources": [], "error": "notes-kb needs-auth", "server_status": "needs-auth"}
    assert kb_usage_from_record(record) == KbUsage("needs-auth")


def test_older_records_without_server_status_still_detect_needs_login():
    assert kb_usage_from_record({"relevant": False, "error": "notes-kb needs-auth"}) == KbUsage("needs-auth")


def test_other_failures_read_as_unavailable():
    assert kb_usage_from_record({"relevant": False, "error": "timed out after 40s"}) == KbUsage("unavailable")


def test_tools_that_failed_to_load_read_as_unavailable():
    record = {"relevant": False, "sources": [], "error": "notes-kb tools unavailable", "server_status": "tools-failed"}
    assert kb_usage_from_record(record) == KbUsage("unavailable")
