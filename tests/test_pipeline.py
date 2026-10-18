import pytest
from conftest import T0, assistant_text, human, tool_result, tool_use

from echo_os.agents.headline.agent import Headline
from echo_os.agents.kb_relevance.agent import KbContext, KbLookup
from echo_os.agents.shared.headless_model import HeadlessModelError
from echo_os.echo.history import EchoHistory
from echo_os.echo.kb_usage import KbUsage
from echo_os.echo.pipeline import EchoJob, EchoPipeline
from echo_os.echo.preferences import Preferences
from echo_os.sessions import SessionRegistry


class FakeHeadline:
    def __init__(self, text="Billing refactor done.", error=None, questions=(), suggestions=()):
        self.text, self.error, self.calls = text, error, []
        self.questions, self.suggestions = tuple(questions), tuple(suggestions)

    def write(self, digest, *, project, kb_context=None):
        self.calls.append({"digest": digest, "project": project, "kb_context": kb_context})
        if self.error:
            raise self.error
        return Headline(self.text, 0.002, 1500, questions=self.questions, suggestions=self.suggestions)


class FakeKb:
    def __init__(self, lookup=None):
        self.result = lookup or KbLookup(None)
        self.calls = 0

    def lookup(self, digest, *, project):
        self.calls += 1
        return self.result


class FakeAnnouncer:
    def __init__(self):
        self.announced = []
        self.resolved = []

    def announce(self, announcement):
        self.announced.append(announcement)

    def resolve(self, session_id):
        self.resolved.append(session_id)

    @property
    def said(self):
        return [a.spoken_text for a in self.announced]


def long_turn(write_transcript, name="t.jsonl"):
    entries = [human("Refactor billing", 0)]
    for i in range(6):
        entries += [tool_use("Edit", 10 + i), tool_result(11 + i)]
    entries.append(assistant_text("All 42 tests pass.", 400))
    return write_transcript(entries, name)


def short_turn(write_transcript):
    return write_transcript([human("hi", 0), assistant_text("hello", 5)], "short.jsonl")


@pytest.fixture
def make_pipeline(tmp_path):
    def _make(headline=None, kb=None, kb_enabled=True):
        parts = dict(
            registry=SessionRegistry(tmp_path / "sessions.json", call_signs=["Alpha", "Bravo"]),
            headline_agent=headline or FakeHeadline(),
            kb_agent=kb if kb is not None else FakeKb(),
            announcer=FakeAnnouncer(),
            history=EchoHistory(tmp_path / "echoes.jsonl"),
            preferences=Preferences(tmp_path / "prefs.json"),
        )
        pipeline = EchoPipeline(**parts, kb_enabled=kb_enabled, min_turn_seconds=180, min_tool_calls=5,
                                max_job_age_seconds=600, tracked_entrypoints={"cli"},
                                spoken_template="{project}, {call_sign}. {headline}")
        return pipeline, parts
    return _make


def hook(event, session_id="s1", **extra):
    return {"hook_event_name": event, "session_id": session_id, "cwd": "/dev/billing-svc", **extra}


def stop_job(path, session_id="s1"):
    return EchoJob(session_id=session_id, transcript_path=str(path), ended_at=T0.timestamp() + 405, queued_at=T0.timestamp() + 405)


def test_project_names_are_spoken_as_words():
    from echo_os.echo.pipeline import spoken_name
    assert spoken_name("web-app") == "web app"
    assert spoken_name("to-do_app") == "to do app"
    assert spoken_name("echo-OS") == "echo OS"
    assert spoken_name("") == ""


def test_spoken_text_is_project_then_call_sign_then_headline():
    from echo_os.echo.pipeline import spoken_text
    template = "{project}, {call_sign}. {headline}"
    assert spoken_text(template, project="web-app", call_sign="Bravo", headline="Done.") == "web app, Bravo. Done."


def test_spoken_text_without_a_project_starts_with_the_call_sign():
    from echo_os.echo.pipeline import spoken_text
    assert spoken_text("{project}, {call_sign}. {headline}", project="", call_sign="Alpha", headline="Done.") == "Alpha. Done."


def test_untracked_entrypoints_are_ignored(make_pipeline):
    pipeline, parts = make_pipeline()
    assert pipeline.handle_hook(hook("SessionStart"), entrypoint="sdk-cli", pid=None, now=1) is None
    assert parts["registry"].active() == []


def test_session_start_assigns_a_call_sign(make_pipeline):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("SessionStart"), entrypoint="cli", pid=42, now=1)
    session = parts["registry"].get("s1")
    assert (session.call_sign, session.project, session.pid) == ("Alpha", "billing-svc", 42)


def test_prompt_marks_working_and_stop_returns_a_job(make_pipeline):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("UserPromptSubmit"), entrypoint="cli", pid=None, now=1)
    assert parts["registry"].get("s1").status == "working"
    job = pipeline.handle_hook(hook("Stop", transcript_path="/t.jsonl", last_assistant_message="Hi"),
                               entrypoint="cli", pid=None, now=9)
    assert parts["registry"].get("s1").status == "idle"
    assert job == EchoJob("s1", "/t.jsonl", ended_at=9, queued_at=9, last_assistant_message="Hi")


def test_session_end_frees_the_sign(make_pipeline):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("SessionStart"), entrypoint="cli", pid=None, now=1)
    pipeline.handle_hook(hook("SessionEnd"), entrypoint="cli", pid=None, now=2)
    assert parts["registry"].active() == []


def test_hook_with_an_unknown_entrypoint_header_is_tracked(make_pipeline):
    """An old hook script that doesn't send the entrypoint shouldn't silently disable echoes."""
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("SessionStart"), entrypoint="", pid=None, now=1)
    assert parts["registry"].get("s1") is not None


def test_long_turn_is_summarized_spoken_and_recorded(make_pipeline, write_transcript):
    kb = FakeKb(KbLookup(KbContext("Billing ships Friday.", ["Roadmap"]), cost_usd=0.004, duration_ms=3000))
    pipeline, parts = make_pipeline(kb=kb)
    pipeline.handle_hook(hook("SessionStart"), entrypoint="cli", pid=None, now=1)
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert parts["announcer"].said == ["billing svc, Alpha. Billing refactor done."]
    assert parts["headline_agent"].calls[0]["kb_context"].context == "Billing ships Friday."
    assert parts["headline_agent"].calls[0]["project"] == "billing-svc"
    stored = parts["history"].recent(5)[0]
    assert stored["id"] == echo.id and stored["headline"] == "Billing refactor done."
    assert stored["kb"]["context"] == "Billing ships Friday."
    assert stored["tool_calls"] == 6
    assert parts["registry"].get("s1").last_headline == "Billing refactor done."


def test_short_turn_is_skipped(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("SessionStart"), entrypoint="cli", pid=None, now=1)
    assert pipeline.process(stop_job(short_turn(write_transcript)), now=T0.timestamp() + 410) is None
    assert parts["announcer"].said == [] and parts["headline_agent"].calls == []
    assert parts["kb_agent"].calls == 0


def test_kb_agent_is_skipped_when_disabled(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline(kb_enabled=False)
    pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert parts["kb_agent"].calls == 0
    assert parts["announcer"].said


def test_kb_failure_still_speaks_and_is_recorded(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline(kb=FakeKb(KbLookup(None, error="Needs authentication")))
    pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert parts["announcer"].said
    assert parts["history"].recent(1)[0]["kb"]["error"] == "Needs authentication"
    assert pipeline.kb_status()["error"] == "Needs authentication"


def test_headline_failure_is_recorded_and_nothing_is_spoken(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline(headline=FakeHeadline(error=HeadlessModelError("timed out")))
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert parts["announcer"].said == []
    assert echo.error == "timed out"
    assert parts["history"].recent(1)[0]["error"] == "timed out"


def test_stale_jobs_are_dropped(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    job = stop_job(long_turn(write_transcript))
    assert pipeline.process(job, now=job.queued_at + 601) is None
    assert parts["headline_agent"].calls == []


def test_missing_transcript_is_skipped(make_pipeline, tmp_path):
    pipeline, parts = make_pipeline()
    assert pipeline.process(stop_job(tmp_path / "missing.jsonl"), now=T0.timestamp() + 410) is None


def test_announcement_carries_what_the_popup_shows(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("SessionStart"), entrypoint="cli", pid=None, now=1)
    pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    announcement = parts["announcer"].announced[0]
    assert (announcement.title, announcement.subtitle, announcement.body) == ("Alpha", "billing-svc", "Billing refactor done.")


def test_session_seen_first_at_stop_still_gets_a_sign(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    echo = pipeline.process(stop_job(long_turn(write_transcript), session_id="late"), now=T0.timestamp() + 410)
    assert echo.call_sign == "Alpha"


def test_replay_speaks_a_stored_echo_again(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert pipeline.replay(echo.id) is True
    assert parts["announcer"].said == ["Alpha. Billing refactor done."] * 2  # no SessionStart, so no project
    assert pipeline.replay("nope") is False


def test_announcement_carries_kb_usage_with_note_count(make_pipeline, write_transcript):
    used = FakeKb(KbLookup(KbContext("Billing ships Friday.", ["Roadmap", "Launch plan"]), server_status="connected"))
    pipeline, parts = make_pipeline(kb=used)
    pipeline.process(stop_job(long_turn(write_transcript, "a.jsonl")), now=T0.timestamp() + 410)
    assert parts["announcer"].announced[-1].kb_usage == KbUsage("used", notes=2)


def test_kb_usage_distinguishes_nothing_relevant_from_logged_out(make_pipeline, write_transcript):
    cases = [(KbLookup(None, server_status="connected"), KbUsage("not-relevant")),
             (KbLookup(None, error="notes-kb needs-auth", server_status="needs-auth"), KbUsage("needs-auth")),
             (KbLookup(None, error="timed out after 40s"), KbUsage("unavailable"))]
    for lookup, expected in cases:
        pipeline, parts = make_pipeline(kb=FakeKb(lookup))
        pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
        assert parts["announcer"].announced[-1].kb_usage == expected


def test_kb_usage_is_off_when_the_kb_agent_is_disabled(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline(kb_enabled=False)
    pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert parts["announcer"].announced[-1].kb_usage == KbUsage("off")


def test_replay_keeps_the_kb_usage(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline(kb=FakeKb(KbLookup(KbContext("ctx", ["n"]), server_status="connected")))
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    pipeline.replay(echo.id)
    assert parts["announcer"].announced[-1].kb_usage == KbUsage("used", notes=1)


def test_kb_lookups_feed_the_auth_light(make_pipeline, write_transcript):
    observed = []

    class Monitor:
        def observe(self, state):
            observed.append(state)

    pipeline, parts = make_pipeline(kb=FakeKb(KbLookup(None, error="notes-kb needs-auth", server_status="needs-auth")))
    pipeline.kb_monitor = Monitor()
    pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    assert observed == ["needs-auth"]


def test_questions_and_suggestions_reach_history_and_the_popup(make_pipeline, write_transcript):
    headline = FakeHeadline("Done, with a question for you on screen.", questions=["Push to main?"],
                            suggestions=["Add a test set"])
    pipeline, parts = make_pipeline(headline=headline)
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    stored = parts["history"].recent(1)[0]
    assert (stored["questions"], stored["suggestions"]) == (["Push to main?"], ["Add a test set"])
    announcement = parts["announcer"].announced[-1]
    assert (announcement.questions, announcement.suggestions) == (("Push to main?",), ("Add a test set",))
    assert announcement.spoken_text.endswith("Alpha. Done, with a question for you on screen.")
    pipeline.replay(echo.id)
    assert parts["announcer"].announced[-1].questions == ("Push to main?",)


def test_announcements_carry_their_session_so_popups_can_be_resolved(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    pipeline.process(stop_job(long_turn(write_transcript), session_id="s9"), now=T0.timestamp() + 410)
    assert parts["announcer"].announced[-1].session_id == "s9"


def test_announcements_carry_the_turn_length_tool_count_and_finish_time(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    announcement = parts["announcer"].announced[-1]
    assert announcement.tool_calls == 6
    assert announcement.duration_seconds == echo.duration_seconds > 0
    assert announcement.finished_at == echo.created_at
    pipeline.replay(echo.id)
    replayed = parts["announcer"].announced[-1]
    assert (replayed.tool_calls, replayed.duration_seconds, replayed.finished_at) == (
        6, echo.duration_seconds, echo.created_at)


def test_announcements_carry_the_working_directory_color(make_pipeline, write_transcript):
    pipeline, parts = make_pipeline()
    echo = pipeline.process(stop_job(long_turn(write_transcript)), now=T0.timestamp() + 410)
    color = parts["registry"].get(echo.session_id).color
    assert color is not None and parts["announcer"].announced[-1].color == color
    pipeline.replay(echo.id)
    assert parts["announcer"].announced[-1].color == color


def test_your_next_message_to_a_session_resolves_its_popups(make_pipeline):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("UserPromptSubmit", session_id="s1"), entrypoint="cli", pid=None, now=5)
    assert parts["announcer"].resolved == ["s1"]


def test_a_session_ending_resolves_its_popups(make_pipeline):
    pipeline, parts = make_pipeline()
    pipeline.handle_hook(hook("SessionStart", session_id="s1"), entrypoint="cli", pid=None, now=1)
    pipeline.handle_hook(hook("SessionEnd", session_id="s1"), entrypoint="cli", pid=None, now=5)
    assert parts["announcer"].resolved == ["s1"]


def test_other_events_do_not_resolve_popups(make_pipeline):
    pipeline, parts = make_pipeline()
    for event in ("SessionStart", "Stop"):
        pipeline.handle_hook(hook(event, session_id="s1", transcript_path="/t"), entrypoint="cli", pid=None, now=5)
    assert parts["announcer"].resolved == []
