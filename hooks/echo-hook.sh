#!/bin/bash
# Claude Code hook: forwards the event JSON to the echo-OS daemon and returns at once.
# Registered by `./echoctl install` for SessionStart, UserPromptSubmit, Stop and SessionEnd.
# It must never slow down or fail a session, so the POST runs detached and every error is ignored.

# echo-OS's own headless summarizer calls set this; never echo ourselves.
[ -n "${ECHO_OS_CHILD:-}" ] && exit 0

payload="$(cat)"
url="http://127.0.0.1:${ECHO_OS_PORT:-8431}/api/hook?entrypoint=${CLAUDE_CODE_ENTRYPOINT:-}&pid=${CLAUDE_PID:-}"
(
    printf '%s' "$payload" | curl -s -m 3 -o /dev/null -X POST \
        -H 'Content-Type: application/json' --data-binary @- "$url"
) >/dev/null 2>&1 &
exit 0
