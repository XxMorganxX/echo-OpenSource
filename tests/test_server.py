import json
import threading
import urllib.error
import urllib.request

import pytest
from test_pipeline import FakeAnnouncer, FakeHeadline, FakeKb

from echo_os.app import EchoApp
from echo_os.echo.history import EchoHistory
from echo_os.echo.pipeline import EchoPipeline
from echo_os.echo.preferences import Preferences
from echo_os.server.server import create_server
from echo_os.sessions import SessionRegistry


class FakeWorker:
    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)


@pytest.fixture
def running(tmp_path):
    prompt = tmp_path / "system_prompt.md"
    prompt.write_text("Original prompt")
    speaker = FakeAnnouncer()
    pipeline = EchoPipeline(
        registry=SessionRegistry(tmp_path / "s.json", call_signs=["Alpha", "Bravo"]),
        headline_agent=FakeHeadline(), kb_agent=FakeKb(), announcer=speaker,
        history=EchoHistory(tmp_path / "e.jsonl"), preferences=Preferences(tmp_path / "p.json"),
        kb_enabled=True, min_turn_seconds=180, min_tool_calls=5, max_job_age_seconds=600,
        tracked_entrypoints={"cli"}, spoken_template="{call_sign}. {headline}", background_detail_chars=160, turn_done_popups=True,
    )
    worker = FakeWorker()
    app = EchoApp(pipeline=pipeline, worker=worker, announcer=speaker, prompt_path=prompt, recent_limit=10,
                  thresholds={"min_turn_seconds": 180, "min_tool_calls": 5}, voice_provider="macos-say")
    server = create_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, app, worker, speaker, prompt
    server.shutdown()
    server.server_close()


def call(method, url, body=None, content_type="application/json", host=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", content_type)
    if host:
        request.add_header("Host", host)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw and response.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as error:
        return error.code, None


def test_health(running):
    base, *_ = running
    assert call("GET", f"{base}/api/health") == (200, {"ok": True})


def test_hook_registers_a_session_and_queues_a_stop(running):
    base, app, worker, *_ = running
    status, _ = call("POST", f"{base}/api/hook?entrypoint=cli&pid=4242",
                     {"hook_event_name": "Stop", "session_id": "s1", "cwd": "/x/proj", "transcript_path": "/t.jsonl"})
    assert status == 204
    assert worker.jobs[0].session_id == "s1"
    status, state = call("GET", f"{base}/api/state")
    assert state["sessions"][0]["call_sign"] == "Alpha"
    assert state["sessions"][0]["pid"] == 4242
    assert state["thresholds"] == {"min_turn_seconds": 180, "min_tool_calls": 5}


def test_hook_with_bad_json_is_rejected(running):
    base, *_ = running
    assert call("POST", f"{base}/api/hook", b"{nope")[0] == 400


def test_prompt_round_trip_writes_the_file(running):
    base, app, worker, speaker, prompt = running
    assert call("GET", f"{base}/api/prompt") == (200, {"prompt": "Original prompt"})
    assert call("PUT", f"{base}/api/prompt", {"prompt": "  New prompt\n"})[0] == 200
    assert prompt.read_text() == "New prompt\n"


def test_empty_prompt_is_rejected(running):
    base, app, worker, speaker, prompt = running
    assert call("PUT", f"{base}/api/prompt", {"prompt": "   "})[0] == 400
    assert prompt.read_text() == "Original prompt"


def test_writes_require_json_content_type(running):
    """Blocks cross-site form posts from a browser page: they can't send application/json without a preflight."""
    base, app, worker, speaker, prompt = running
    assert call("PUT", f"{base}/api/prompt", {"prompt": "x"}, content_type="text/plain")[0] == 415
    assert prompt.read_text() == "Original prompt"


def test_foreign_host_header_is_rejected(running):
    """DNS-rebinding guard."""
    base, *_ = running
    assert call("GET", f"{base}/api/state", host="evil.example.com")[0] == 403


def test_mute_toggle(running):
    base, app, *_ = running
    assert call("POST", f"{base}/api/mute", {"muted": True}) == (200, {"muted": True})
    assert call("GET", f"{base}/api/state")[1]["muted"] is True


def test_replay_unknown_echo_is_404(running):
    base, *_ = running
    assert call("POST", f"{base}/api/echoes/nope/replay", {})[0] == 404


def test_replay_known_echo(running):
    base, app, worker, speaker, prompt = running
    app.pipeline.history.append({"id": "abc", "spoken_text": "Alpha. Done."})
    assert call("POST", f"{base}/api/echoes/abc/replay", {})[0] == 200
    assert speaker.said == ["Alpha. Done."]


def test_index_is_served(running):
    base, *_ = running
    status, body = call("GET", f"{base}/")
    assert status == 200 and b"echo" in body.lower()


def test_speak_queues_through_the_app(running):
    base, app, worker, speaker, prompt = running
    assert call("POST", f"{base}/api/speak", {"text": "Build finished.", "title": "CI"})[0] == 202
    announcement = speaker.announced[0]
    assert (announcement.spoken_text, announcement.title, announcement.body) == ("Build finished.", "CI", "Build finished.")


def test_speak_requires_text(running):
    base, *_ = running
    assert call("POST", f"{base}/api/speak", {"text": "  "})[0] == 400


def test_spoken_messages_from_other_tools_have_no_kb_indicator(running):
    base, app, worker, speaker, prompt = running
    call("POST", f"{base}/api/speak", {"text": "Hi."})
    assert speaker.announced[0].kb_usage is None


class FakeMonitor:
    def __init__(self):
        self.checks = 0

    def snapshot(self):
        return {"state": "connected", "checked_at": 1.0, "source": "check"}

    def check(self):
        self.checks += 1


def test_state_includes_the_kb_auth_light(running):
    base, app, *_ = running
    app.kb_monitor = FakeMonitor()
    assert call("GET", f"{base}/api/state")[1]["kb_auth"]["state"] == "connected"


def test_kb_check_runs_a_fresh_check(running):
    base, app, *_ = running
    app.kb_monitor = FakeMonitor()
    status, body = call("POST", f"{base}/api/kb/check", {})
    assert status == 200 and body["state"] == "connected" and app.kb_monitor.checks == 1


def test_state_includes_the_directory_palette(running):
    from echo_os import settings
    base, *_ = running
    assert call("GET", f"{base}/api/state")[1]["directory_colors"] == list(settings.DIRECTORY_COLORS)
