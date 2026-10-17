import pytest

from echo_os.agents.headline import config
from echo_os.agents.headline.agent import HeadlineAgent, spoken_duration
from echo_os.agents.kb_relevance.agent import KbContext
from echo_os.agents.shared.headless_model import HeadlessModelError, ModelResult
from echo_os.transcript import TurnDigest


class FakeModel:
    def __init__(self, text="Done.", error=None):
        self.text, self.error, self.requests = text, error, []

    def run(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ModelResult(text=self.text, structured=None, cost_usd=0.002, duration_ms=1500)


DIGEST = TurnDigest(ask="Refactor billing", response="All 42 tests pass.", tool_calls=12, duration_seconds=400)


def test_request_uses_the_editable_prompt_file_and_config_model(tmp_path, monkeypatch):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("CUSTOM PROMPT\n")
    monkeypatch.setattr(config, "SYSTEM_PROMPT_PATH", prompt)
    model = FakeModel()
    HeadlineAgent(model).write(DIGEST, project="billing-svc")
    request = model.requests[0]
    assert request.system_prompt == "CUSTOM PROMPT"
    assert request.model == config.MODEL
    assert request.mcp_servers == {} and request.allowed_tools == []


def test_user_message_carries_the_turn_but_no_kb_section_without_context():
    model = FakeModel()
    HeadlineAgent(model).write(DIGEST, project="billing-svc")
    message = model.requests[0].user_message
    assert "billing-svc" in message and "Refactor billing" in message and "All 42 tests pass." in message
    assert "6 minutes" in message
    assert "<kb>" not in message


def test_kb_context_is_included_when_given():
    model = FakeModel()
    HeadlineAgent(model).write(DIGEST, project="p", kb_context=KbContext(context="Billing ships Friday.", sources=["Roadmap"]))
    assert "Billing ships Friday." in model.requests[0].user_message


def test_long_inputs_are_truncated(monkeypatch):
    monkeypatch.setattr(config, "MAX_RESPONSE_CHARS", 50)
    model = FakeModel()
    HeadlineAgent(model).write(TurnDigest("a", "x" * 500, 1, 1), project="p")
    assert "x" * 51 not in model.requests[0].user_message


def test_markdown_and_extra_whitespace_are_stripped_from_the_headline():
    result = HeadlineAgent(FakeModel("**Done**:  the `billing` refactor\n\n- all tests pass")).write(DIGEST, project="p")
    assert result.text == "Done: the billing refactor all tests pass"


def test_headline_is_capped(monkeypatch):
    monkeypatch.setattr(config, "MAX_HEADLINE_CHARS", 20)
    result = HeadlineAgent(FakeModel("word " * 30)).write(DIGEST, project="p")
    assert len(result.text) <= 20


def test_empty_headline_is_an_error():
    with pytest.raises(HeadlessModelError):
        HeadlineAgent(FakeModel("   ")).write(DIGEST, project="p")


def test_result_reports_cost_and_latency():
    result = HeadlineAgent(FakeModel()).write(DIGEST, project="p")
    assert (result.cost_usd, result.duration_ms) == (0.002, 1500)


@pytest.mark.parametrize("seconds,spoken", [(45, "45 seconds"), (60, "1 minute"), (400, "6 minutes"),
                                            (3600, "1 hour"), (3900, "1 hour 5 minutes")])
def test_spoken_duration(seconds, spoken):
    assert spoken_duration(seconds) == spoken
