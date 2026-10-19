import threading

from echo_os.echo.announcer import Announcement, Announcer
from echo_os.echo.kb_usage import KbUsage
from echo_os.echo.preferences import Preferences
from echo_os.voice import VoiceError


class RecordingVoice:
    def __init__(self, fail_on=None):
        self.events, self.fail_on = [], fail_on
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def speak(self, text):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.events.append(("speak", text))
        with self.lock:
            self.active -= 1
        if text == self.fail_on:
            raise VoiceError("x")


class RecordingPopup:
    def __init__(self, events):
        self.events = events

    def show(self, announcement, *, speaking):
        self.events.append(("popup", announcement.title) if speaking else ("popup muted", announcement.title))

    def finished_speaking(self, announcement):
        self.events.append(("finished", announcement.title))


def make(tmp_path, **voice_kwargs):
    voice = RecordingVoice(**voice_kwargs)
    prefs = Preferences(tmp_path / "p.json")
    announcer = Announcer(voice=voice, preferences=prefs, popup=RecordingPopup(voice.events))
    return announcer, voice, prefs


def item(name):
    return Announcement(spoken_text=f"{name}. done", title=name, subtitle="proj", body="done")


def test_each_popup_appears_as_its_speech_starts_one_at_a_time(tmp_path):
    announcer, voice, _ = make(tmp_path)
    for name in ("Alpha", "Bravo", "Charlie"):
        announcer.announce(item(name))
    announcer.start()
    announcer.stop()
    assert voice.events == [("popup", "Alpha"), ("speak", "Alpha. done"), ("finished", "Alpha"),
                            ("popup", "Bravo"), ("speak", "Bravo. done"), ("finished", "Bravo"),
                            ("popup", "Charlie"), ("speak", "Charlie. done"), ("finished", "Charlie")]
    assert voice.max_active == 1


def test_mute_is_checked_at_play_time_and_popups_still_show(tmp_path):
    announcer, voice, prefs = make(tmp_path)
    announcer.announce(item("Alpha"))
    prefs.set_muted(True)  # muted after queueing, before playing
    announcer.start()
    announcer.stop()
    assert voice.events == [("popup muted", "Alpha")]


def test_voice_errors_do_not_stop_the_queue(tmp_path):
    announcer, voice, _ = make(tmp_path, fail_on="Alpha. done")
    announcer.announce(item("Alpha"))
    announcer.announce(item("Bravo"))
    announcer.start()
    announcer.stop()
    assert ("speak", "Bravo. done") in voice.events
    # The speaking indicator must stop even when the voice failed.
    assert ("finished", "Alpha") in voice.events


def test_announcer_works_without_a_popup(tmp_path):
    voice = RecordingVoice()
    announcer = Announcer(voice=voice, preferences=Preferences(tmp_path / "p.json"), popup=None)
    announcer.announce(item("Alpha"))
    announcer.start()
    announcer.stop()
    assert voice.events == [("speak", "Alpha. done")]


def test_popup_receives_the_kb_indicator(tmp_path):
    received = []

    class Popup:
        def show(self, announcement, *, speaking):
            received.append(announcement.kb_usage)

        def finished_speaking(self, announcement):
            pass

    announcer = Announcer(voice=RecordingVoice(), preferences=Preferences(tmp_path / "p.json"), popup=Popup())
    announcer.announce(Announcement(spoken_text="x", title="A", subtitle="p", body="x", kb_usage=KbUsage("used", 1)))
    announcer.start()
    announcer.stop()
    assert received == [KbUsage("used", 1)]


def test_resolve_reaches_the_popup_immediately_not_behind_the_queue(tmp_path):
    resolved = []

    class Popup:
        def show(self, announcement, *, speaking):
            pass

        def finished_speaking(self, announcement):
            pass

        def resolve(self, session_id):
            resolved.append(session_id)

    announcer = Announcer(voice=RecordingVoice(), preferences=Preferences(tmp_path / "p.json"), popup=Popup())
    announcer.announce(item("Alpha"))  # queued, thread not started
    announcer.resolve("s1")
    assert resolved == ["s1"]


def test_resolve_without_a_popup_is_harmless(tmp_path):
    Announcer(voice=RecordingVoice(), preferences=Preferences(tmp_path / "p.json"), popup=None).resolve("s1")


def test_announcements_without_spoken_text_only_pop_up(tmp_path):
    announcer, voice, _ = make(tmp_path)
    announcer._handle(Announcement(spoken_text="", title="Alpha", subtitle="p", body="Done."))
    assert voice.events == [("popup muted", "Alpha")]
