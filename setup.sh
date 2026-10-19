#!/usr/bin/env bash
# echo-OS first-time setup: checks prerequisites, creates ./venv, installs, and runs the tests.
# It changes nothing outside this folder. `./echoctl install` is the step that adds the background
# agent and the Claude Code hooks, so it stays a separate, deliberate step.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python3.13}"

echo "=== echo-OS setup ==="

[ "$(uname -s)" = Darwin ] || { echo "Error: echo-OS runs on macOS only." >&2; exit 1; }
command -v "$PYTHON" >/dev/null 2>&1 || {
    echo "Error: $PYTHON not found. Install it with 'brew install python@3.13'," >&2
    echo "or point PYTHON at a Python 3.13: PYTHON=/path/to/python3.13 ./setup.sh" >&2
    exit 1
}
if ! command -v claude >/dev/null 2>&1; then
    echo "Warning: the claude CLI isn't on your PATH. echo-OS makes its model calls through Claude Code:" >&2
    echo "  install it (https://docs.anthropic.com/en/docs/claude-code) and run 'claude' once to sign in." >&2
fi

if [ ! -x venv/bin/python ]; then
    echo "Creating ./venv ..."
    "$PYTHON" -m venv venv
fi
echo "Installing dependencies ..."
./venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt -e .

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example (every setting in it is optional)."
fi

echo "Running the tests ..."
./venv/bin/python -m pytest -q

echo
echo "=== Setup complete ==="
echo "Next:"
echo "  ./echoctl install   # start the menu bar app at login and add the Claude Code hooks"
echo "  Then follow 'Check it works' in README.md."
echo "  Using Claude Code on this repo? CLAUDE.md has the project context."
