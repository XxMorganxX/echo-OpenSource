#!/usr/bin/env bash
# Publication check: fails if a secret, personal detail or private file is in anything git would
# publish: every commit on every local branch, their messages and authors, plus what is staged.
#
#   ./scripts/check-publication.sh                 # run it
#   ./scripts/check-publication.sh --install-hook  # have git run it before every push
#
# The generic patterns live here. Strings that are private to you (a private server's domain, a
# private project's name) go one per line in .publication-denylist, which git ignores, so the list of
# what you're keeping private is never published itself. Lines starting with # are comments.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

DENYLIST=.publication-denylist
HOOK=.git/hooks/pre-push
HOOK_MARKER="# echo-OS publication check"

if [ "${1:-}" = --install-hook ]; then
    if [ -e "$HOOK" ] && ! grep -qF "$HOOK_MARKER" "$HOOK"; then
        echo "$HOOK already exists and isn't this check; add a call to scripts/check-publication.sh to it by hand." >&2
        exit 1
    fi
    printf '#!/bin/sh\n%s\nexec "$(git rev-parse --show-toplevel)/scripts/check-publication.sh"\n' "$HOOK_MARKER" > "$HOOK"
    chmod +x "$HOOK"
    echo "Installed $HOOK: git now runs this check before every push."
    exit 0
fi

failures=0
fail() { echo "FAIL  $*" >&2; failures=$((failures + 1)); }

# 1. Files that must never be tracked. .env.example is the one allowed .env file.
forbidden='(^|/)(\.env(\..+)?|kb\.json|credentials\.json|service-account[^/]*\.json|[^/]*\.(pem|key|p12|pfx|jks))$|^(state|tasks|secrets|\.secrets|venv|\.venv)/'
while IFS= read -r path; do
    [ "$path" = .env.example ] || fail "tracked file that must stay private: $path"
done < <(git ls-files | grep -E "$forbidden" || true)

# 2. Content: every commit's diff and message, plus the staged changes, one line each, prefixed with
#    where it came from so a hit can name the commit.
history="$(mktemp)"
trap 'rm -f "$history"' EXIT
{
    git log -p --all --format='@@where commit %h%n%B' | awk '/^@@where /{where=$3; next} {print where "\t" $0}'
    git diff --cached | awk '{print "staged\t" $0}'
    git log --all --format='%an <%ae>%n%cn <%ce>' | sort -u | awk '{print "author\t" $0}'
} > "$history"

# report <label> <grep option> <pattern> [<allowed pattern>]: names the commits a match is in, and
# never prints the matching text. Matches that also fit <allowed pattern> (placeholders) don't count.
report() {
    local matches where
    matches="$(cut -f2- "$history" | grep -n "$2" -e "$3" || true)"
    [ -z "${4:-}" ] || matches="$(printf '%s\n' "$matches" | grep -vE "$4" || true)"
    [ -n "$matches" ] || return 0
    where="$(printf '%s\n' "$matches" | cut -d: -f1 \
        | awk -F'\t' 'NR == FNR { wanted[$1]; next } FNR in wanted { print $1 }' - "$history" \
        | sort -u | head -5 | tr '\n' ' ')"
    fail "$1 in: $where"
}

# Secrets (patterns from the opensource-pipeline sanitizer, in POSIX ERE).
report "API key"            -iE '(api[_-]?key|apikey|api[_-]?secret)[A-Za-z0-9_]*[[:space:]]*[=:][[:space:]]*["'\'']?[A-Za-z0-9+/=_-]{16,}'
report "AWS access key"     -E 'AKIA[0-9A-Z]{16}'
report "AWS secret"         -iE '(aws_secret_access_key|aws_secret)[[:space:]]*[=:][[:space:]]*["'\'']?[A-Za-z0-9+/=]{20,}'
report "database URL with password" -E '(postgres|postgresql|mysql|mongodb|redis)://[^:/[:space:]]+:[^@[:space:]]+@'
report "JWT"                -E 'eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+'
report "private key"        -E '-----BEGIN[[:space:]]+(RSA[[:space:]]+|EC[[:space:]]+|DSA[[:space:]]+|OPENSSH[[:space:]]+)?PRIVATE KEY-----'
report "GitHub token"       -E '(gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{22,})'
report "Anthropic/OpenAI key" -E 'sk-(ant-)?[A-Za-z0-9_-]{24,}'
report "Google OAuth secret" -E 'GOCSPX-[A-Za-z0-9_-]+'
report "Slack webhook"      -E 'hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/'
report "SendGrid key"       -E 'SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}'

# Personal details.
report "personal email address" -iE '[A-Za-z0-9._%+-]+@(gmail|googlemail|yahoo|hotmail|outlook|protonmail|proton|icloud|me)\.(com|net|org|me)'
report "private IP address" -E '(^|[^0-9.])(192\.168\.[0-9]{1,3}\.[0-9]{1,3}|10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})([^0-9.]|$)'
report "home folder path"   -E '/(Users|home)/[A-Za-z][A-Za-z0-9_-]*/' '/(Users|home)/(me|you|user|username|example|Shared)/'
report "ssh login"          -E 'ssh[[:space:]]+[A-Za-z0-9._-]+@'

# Your own private strings, if you keep a denylist.
denied=0
if [ -f "$DENYLIST" ]; then
    line_number=0
    while IFS= read -r private || [ -n "$private" ]; do
        line_number=$((line_number + 1))
        case "$private" in ''|'#'*) continue ;; esac
        denied=$((denied + 1))
        report "string from line $line_number of $DENYLIST" -F "$private"
    done < "$DENYLIST"
fi

if [ "$failures" -gt 0 ]; then
    echo "Publication check failed: $failures problem(s). Nothing private may be pushed; fix these first." >&2
    exit 1
fi
commits="$(git rev-list --all | wc -l | tr -d ' ')"
if [ -f "$DENYLIST" ]; then
    echo "Publication check passed: $commits commits, staged changes, and $denied private strings checked."
else
    echo "Publication check passed: $commits commits and staged changes checked (no $DENYLIST, so generic checks only)."
fi
