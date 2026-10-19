import subprocess

from echo_os.terminal_focus import Process, TerminalTarget, find_terminal, focus_session, parse_process_table

TERMINAL = "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"

# Seen live: claude under a login shell in a Terminal tab.
IN_TERMINAL = {
    19409: Process(ppid=19405, tty="ttys013", command="claude"),
    19405: Process(ppid=19371, tty="ttys013", command="/bin/sh"),
    19371: Process(ppid=19370, tty="ttys013", command="-zsh"),
    19370: Process(ppid=687, tty="ttys013", command="login"),
    687: Process(ppid=1, tty="??", command=TERMINAL),
}


class FakeRun:
    def __init__(self, stdout="found\n", returncode=0):
        self.calls, self.stdout, self.returncode = [], stdout, returncode

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.returncode, stdout=self.stdout, stderr="")


def test_parses_commands_with_spaces():
    table = parse_process_table("  687     1 ??       /Applications/Visual Studio Code.app/Contents/MacOS/Electron\n")
    assert table == {687: Process(ppid=1, tty="??", command="/Applications/Visual Studio Code.app/Contents/MacOS/Electron")}


def test_finds_the_terminal_app_and_tty_of_a_session():
    assert find_terminal(19409, IN_TERMINAL) == TerminalTarget(
        app_path="/System/Applications/Utilities/Terminal.app", tty="/dev/ttys013")


def test_picks_the_outermost_app_when_helpers_are_nested():
    helper = "/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/Code Helper (Plugin)"
    table = {
        50: Process(ppid=40, tty="ttys002", command="claude"),
        40: Process(ppid=30, tty="ttys002", command="-zsh"),
        30: Process(ppid=20, tty="??", command=helper),
        20: Process(ppid=1, tty="??", command="/Applications/Visual Studio Code.app/Contents/MacOS/Electron"),
    }
    assert find_terminal(50, table).app_path == "/Applications/Visual Studio Code.app"


def test_no_terminal_inside_tmux():
    table = {
        50: Process(ppid=40, tty="ttys004", command="claude"),
        40: Process(ppid=30, tty="ttys004", command="-zsh"),
        30: Process(ppid=1, tty="??", command="tmux"),
    }
    assert find_terminal(50, table) is None


def test_no_terminal_for_a_process_that_is_gone():
    assert find_terminal(999, IN_TERMINAL) is None


def test_terminal_tab_is_selected_by_tty():
    run = FakeRun()
    assert focus_session(19409, processes=IN_TERMINAL, run=run) is True
    assert len(run.calls) == 1
    assert run.calls[0][0] == "osascript" and run.calls[0][-1] == "/dev/ttys013"


def test_app_is_brought_forward_when_its_tab_is_not_found():
    run = FakeRun(stdout="missing\n")
    assert focus_session(19409, processes=IN_TERMINAL, run=run) is True
    assert run.calls[-1] == ["open", "-a", "/System/Applications/Utilities/Terminal.app"]


def test_unscriptable_apps_are_only_brought_forward():
    table = {
        50: Process(ppid=20, tty="ttys002", command="claude"),
        20: Process(ppid=1, tty="??", command="/Applications/Ghostty.app/Contents/MacOS/ghostty"),
    }
    run = FakeRun()
    assert focus_session(50, processes=table, run=run) is True
    assert run.calls == [["open", "-a", "/Applications/Ghostty.app"]]


def test_nothing_to_focus_without_a_pid():
    run = FakeRun()
    assert focus_session(None, processes=IN_TERMINAL, run=run) is False
    assert run.calls == []


def test_nothing_to_focus_without_a_terminal_app():
    run = FakeRun()
    assert focus_session(999, processes=IN_TERMINAL, run=run) is False
    assert run.calls == []
