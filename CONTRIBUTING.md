# Contributing

Thanks for helping. echo-OS is small, so the bar is simple: a change should be tested, documented
in the same commit, and never publish anything private.

## Development setup

```bash
git clone https://github.com/XxMorganxX/echo-OpenSource.git echo-os
cd echo-os
./setup.sh                                  # venv, dependencies, tests
./scripts/check-publication.sh --install-hook   # run the publication check before every push
```

You only need `./echoctl install` to try changes live. `./echoctl restart` picks up code changes;
`./echoctl logs` shows what the agent is doing.

## Making a change

1. Open an issue first for anything bigger than a bug fix, so we can agree on the approach.
2. Branch from `main`.
3. Write the test first for real logic (a bug fix starts with a test that reproduces the bug).
   Tests never call a model, speak or need network; the existing tests show how each is faked.
4. Keep `./echoctl test` passing.
5. Update the docs in the same commit:
   - `docs/spec.md` for behavior;
   - the agent's docs under `echo_os/agents/<agent>/` if an agent changes;
   - `README.md` for anything a user does differently.
6. Open a pull request that says what changed and why.

## Code style

- Follow the code around you. Names say what something is; comments say why.
- Every tunable value lives in `echo_os/settings.py`, every prompt and agent parameter in that
  agent's `config.py`. Nothing tunable is defined inline.
- Providers that might be swapped (voice, model, knowledge base) sit behind an interface. Callers
  depend on the interface, never on the provider.
- No new dependencies without a reason in the pull request.

## Keep it public-safe

Never commit `kb.json`, `.env`, `state/` or `tasks/`. They hold your knowledge-base connection,
keys, echo history and notes, and git ignores them. `scripts/check-publication.sh` fails if anything
private or secret is in a commit, a commit message or the staged changes. For strings only you know
are private, list them in a gitignored `.publication-denylist`, one per line.

## Reporting issues

Use the issue templates. For a bug, include:
- your macOS version;
- `claude --version`;
- what you expected;
- the relevant lines from `./echoctl logs`.

Read the log lines before you paste them: they can include text from your sessions.

## Using Claude Code

This repo has a `CLAUDE.md` with its commands, architecture and rules. Run `claude` in the repo and
it's read automatically.
