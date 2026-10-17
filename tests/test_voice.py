import json
import subprocess

import pytest

from echo_os.voice import create_voice
from echo_os.voice.macos_say import MacOsSay
from echo_os.voice.openai_tts import OpenAiTts
from echo_os.voice.interface import VoiceError


class FakeRunner:
    def __init__(self, returncode=0):
        self.returncode, self.calls = returncode, []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.returncode, "", "err")


def test_say_passes_voice_and_rate():
    runner = FakeRunner()
    MacOsSay(voice="Samantha", rate_wpm=190, timeout_seconds=5, run=runner).speak("Alpha. Done.")
    assert runner.calls[0] == ["say", "-v", "Samantha", "-r", "190", "--", "Alpha. Done."]


def test_say_without_voice_uses_the_system_default():
    runner = FakeRunner()
    MacOsSay(voice="", rate_wpm=190, timeout_seconds=5, run=runner).speak("hi")
    assert "-v" not in runner.calls[0]


def test_say_failure_raises_voice_error():
    with pytest.raises(VoiceError):
        MacOsSay(voice="", rate_wpm=190, timeout_seconds=5, run=FakeRunner(returncode=1)).speak("hi")


def test_openai_posts_the_text_and_plays_the_audio(tmp_path):
    posted = {}

    def fake_post(url, body, headers, timeout):
        posted.update(url=url, body=json.loads(body), headers=headers)
        return b"MP3"

    runner = FakeRunner()
    OpenAiTts(api_key="sk-x", model="gpt-4o-mini-tts", voice="alloy", instructions="calm",
              timeout_seconds=5, workdir=tmp_path, post=fake_post, run=runner).speak("Bravo. Done.")
    assert posted["body"] == {"model": "gpt-4o-mini-tts", "voice": "alloy", "input": "Bravo. Done.",
                              "instructions": "calm", "response_format": "mp3"}
    assert posted["headers"]["Authorization"] == "Bearer sk-x"
    assert runner.calls[0][0] == "afplay"
    assert not list(tmp_path.glob("*.mp3"))  # temp audio is cleaned up


def test_factory_defaults_to_say():
    assert isinstance(create_voice("macos-say"), MacOsSay)


def test_factory_falls_back_to_say_without_an_openai_key(monkeypatch):
    from echo_os import settings
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert isinstance(create_voice("openai"), MacOsSay)


def test_factory_rejects_unknown_providers():
    with pytest.raises(ValueError):
        create_voice("nope")
