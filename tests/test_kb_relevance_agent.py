from echo_os.agents.kb_relevance import config
from echo_os.agents.kb_relevance.agent import KbRelevanceAgent
from echo_os.agents.shared.headless_model import HeadlessModelError, ModelResult
from echo_os.transcript import TurnDigest


class FakeModel:
    def __init__(self, structured=None, error=None, kb_status="connected"):
        self.structured, self.error, self.kb_status, self.requests = structured, error, kb_status, []

    def run(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return ModelResult(text="", structured=self.structured, cost_usd=0.004, duration_ms=3000,
                           mcp_status={config.KB_MCP_SERVER_NAME: self.kb_status})


DIGEST = TurnDigest(ask="Update the Invoice Tracker reminder emails", response="Done.", tool_calls=9, duration_seconds=500)


def test_request_attaches_only_kb_mcp_and_its_read_tools():
    model = FakeModel({"relevant": False, "context": "", "sources": []})
    KbRelevanceAgent(model).lookup(DIGEST, project="invoice-tracker")
    request = model.requests[0]
    assert request.mcp_servers == {config.KB_MCP_SERVER_NAME: {"type": "http", "url": config.KB_MCP_URL}}
    assert request.allowed_tools == config.ALLOWED_TOOLS
    assert request.json_schema == config.OUTPUT_SCHEMA
    assert "Invoice Tracker reminder emails" in request.user_message


def test_relevant_answer_becomes_context():
    lookup = KbRelevanceAgent(FakeModel({"relevant": True, "context": "The CRM is the team's SaaS product.", "sources": ["FOUNDING"]})).lookup(DIGEST, project="p")
    assert lookup.context.context == "The CRM is the team's SaaS product."
    assert lookup.context.sources == ["FOUNDING"]
    assert lookup.error is None and lookup.cost_usd == 0.004


def test_not_relevant_gives_no_context():
    lookup = KbRelevanceAgent(FakeModel({"relevant": False, "context": "x", "sources": []})).lookup(DIGEST, project="p")
    assert lookup.context is None and lookup.error is None


def test_relevant_but_empty_context_gives_no_context():
    lookup = KbRelevanceAgent(FakeModel({"relevant": True, "context": "  ", "sources": []})).lookup(DIGEST, project="p")
    assert lookup.context is None


def test_model_failure_fails_open_with_the_reason():
    lookup = KbRelevanceAgent(FakeModel(error=HeadlessModelError("timed out"))).lookup(DIGEST, project="p")
    assert lookup.context is None and "timed out" in lookup.error


def test_missing_structured_output_fails_open():
    lookup = KbRelevanceAgent(FakeModel(None)).lookup(DIGEST, project="p")
    assert lookup.context is None and lookup.error


def test_context_is_capped(monkeypatch):
    monkeypatch.setattr(config, "MAX_CONTEXT_CHARS", 10)
    lookup = KbRelevanceAgent(FakeModel({"relevant": True, "context": "y" * 100, "sources": []})).lookup(DIGEST, project="p")
    assert len(lookup.context.context) <= 10


def test_unconnected_kb_server_is_an_error_not_a_no():
    """Without this an expired login reads as 'nothing relevant' forever."""
    lookup = KbRelevanceAgent(FakeModel({"relevant": False, "context": "", "sources": []}, kb_status="needs-auth")).lookup(DIGEST, project="p")
    assert lookup.context is None
    assert lookup.error == "notes-kb needs-auth"


def test_lookup_reports_the_server_status_it_saw():
    connected = KbRelevanceAgent(FakeModel({"relevant": False, "context": "", "sources": []})).lookup(DIGEST, project="p")
    needs_auth = KbRelevanceAgent(FakeModel({"relevant": False, "context": "", "sources": []}, kb_status="needs-auth")).lookup(DIGEST, project="p")
    failed = KbRelevanceAgent(FakeModel(error=HeadlessModelError("timed out"))).lookup(DIGEST, project="p")
    assert (connected.server_status, needs_auth.server_status, failed.server_status) == ("connected", "needs-auth", None)
