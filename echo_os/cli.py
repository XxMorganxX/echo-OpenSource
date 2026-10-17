"""Run one agent by hand against a transcript, bypassing the hook and the long-horizon gate.

    ./echoctl headline <transcript.jsonl>   # KB agent + headline, printed (not spoken)
    ./echoctl kb <transcript.jsonl>         # KB relevance agent only
    ./echoctl say "text"                    # voice check
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from echo_os import settings
from echo_os.agents.headline.agent import HeadlineAgent
from echo_os.agents.kb_relevance.agent import KbRelevanceAgent
from echo_os.agents.shared.headless_model import ClaudeCodeHeadless
from echo_os.transcript import is_long_horizon, read_last_turn
from echo_os.voice import create_voice


def _digest(path: str):
    digest = read_last_turn(path, ended_at=time.time())
    if digest is None:
        sys.exit(f"No human prompt found in the last turn of {path}")
    long_horizon = is_long_horizon(digest, min_seconds=settings.MIN_TURN_SECONDS, min_tool_calls=settings.MIN_TOOL_CALLS)
    print(f"turn: {digest.duration_seconds:.0f}s, {digest.tool_calls} tool calls, long-horizon={long_horizon}", file=sys.stderr)
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("headline", "kb"):
        command = sub.add_parser(name)
        command.add_argument("transcript")
        command.add_argument("--project", default=None)
    say = sub.add_parser("say")
    say.add_argument("text")
    args = parser.parse_args()

    if args.command == "say":
        create_voice().speak(args.text)
        return

    model = ClaudeCodeHeadless(binary=settings.CLAUDE_BINARY, workdir=settings.HEADLESS_WORKDIR,
                               child_env_flag=settings.CHILD_ENV_FLAG)
    digest = _digest(args.transcript)
    project = args.project or Path(args.transcript).parent.name
    kb = KbRelevanceAgent(model).lookup(digest, project=project)
    print(json.dumps({"kb_context": kb.context.context if kb.context else None,
                      "kb_sources": kb.context.sources if kb.context else [],
                      "kb_error": kb.error, "kb_cost_usd": kb.cost_usd, "kb_ms": kb.duration_ms}, indent=2))
    if args.command == "headline":
        headline = HeadlineAgent(model).write(digest, project=project, kb_context=kb.context)
        print(json.dumps({"headline": headline.text, "cost_usd": headline.cost_usd, "ms": headline.duration_ms}, indent=2))


if __name__ == "__main__":
    main()
