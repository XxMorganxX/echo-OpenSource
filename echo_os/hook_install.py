"""Adds and removes echo-OS's hook entries in a Claude Code settings.json, leaving all else alone.

Our entries are recognised by the hook script's file name, so reinstalling from a moved checkout
replaces the stale command instead of adding a second one.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

HOOK_SCRIPT_NAME = "echo-hook.sh"
HOOK_TIMEOUT_SECONDS = 5


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON; fix it before installing hooks ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".echo-os.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _is_ours(hook: dict) -> bool:
    return HOOK_SCRIPT_NAME in str(hook.get("command", ""))


def _without_ours(groups: list) -> list:
    kept = []
    for group in groups:
        hooks = [hook for hook in group.get("hooks", []) if not _is_ours(hook)]
        if hooks:
            kept.append({**group, "hooks": hooks})
    return kept


def install_hooks(settings_path: Path, *, command: str, events: list[str]) -> None:
    data = _load(settings_path)
    backup = settings_path.with_name(settings_path.name + ".echo-os.bak")
    if settings_path.exists() and not backup.exists():
        shutil.copy2(settings_path, backup)
    hooks = data.setdefault("hooks", {})
    for event in events:
        groups = _without_ours(hooks.get(event, []))
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}]})
        hooks[event] = groups
    _save(settings_path, data)


def uninstall_hooks(settings_path: Path) -> None:
    data = _load(settings_path)
    hooks = data.get("hooks", {})
    for event in list(hooks):
        groups = _without_ours(hooks[event])
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    _save(settings_path, data)


def main() -> None:
    from echo_os import settings

    parser = argparse.ArgumentParser(description="Install or remove echo-OS Claude Code hooks")
    parser.add_argument("action", choices=["install", "uninstall"])
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = parser.parse_args()
    if args.action == "install":
        script = settings.APP_ROOT / "hooks" / HOOK_SCRIPT_NAME
        install_hooks(args.settings, command=f"ECHO_OS_PORT={settings.SERVER_PORT} '{script}'", events=settings.HOOK_EVENTS)
        print(f"Hooks installed in {args.settings} for {', '.join(settings.HOOK_EVENTS)}")
    else:
        uninstall_hooks(args.settings)
        print(f"Hooks removed from {args.settings}")


if __name__ == "__main__":
    main()
