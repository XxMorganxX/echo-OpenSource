from echo_os import settings
from echo_os.echo.kb_usage import KbUsage
from echo_os.menubar.popup import build_card, display_seconds


def test_short_headlines_stay_up_for_the_minimum():
    assert display_seconds("Done.") == settings.POPUP_MIN_SECONDS


def test_long_headlines_get_reading_time_up_to_the_cap():
    assert display_seconds("word " * 30) == min(settings.POPUP_MAX_SECONDS, 30 / settings.POPUP_READING_WORDS_PER_SECOND + 2)
    assert display_seconds("word " * 500) == settings.POPUP_MAX_SECONDS


def test_card_grows_with_its_text():
    short = build_card(title="Alpha", subtitle="p", body="Done.", on_click=None)
    long = build_card(title="Alpha", subtitle="p", body="word " * 60, on_click=None)
    assert short.frame().size.width == long.frame().size.width == settings.POPUP_WIDTH
    assert long.frame().size.height > short.frame().size.height


def _kb_status(card):
    from AppKit import NSImageView, NSTextField
    icons = [view for view in card.subviews() if isinstance(view, NSImageView)]
    labels = [view.stringValue() for view in card.subviews() if isinstance(view, NSTextField) and view.stringValue().startswith("KB")]
    return icons, labels


def card_with(usage):
    return build_card(title="A", subtitle="p", body="Done.", on_click=None, kb_usage=usage)


def test_each_kb_state_has_its_own_label_and_tooltip():
    expected = {
        KbUsage("used", notes=2): ("KB · 2 notes", "Informed by your knowledge base (2 notes)"),
        KbUsage("used", notes=1): ("KB · 1 note", "Informed by your knowledge base (1 note)"),
        KbUsage("not-relevant"): ("KB · nothing relevant", "Knowledge base searched; nothing relevant"),
        KbUsage("needs-auth"): ("KB · needs login", "notes-kb needs login: in Claude Code run /mcp, pick notes-kb, Authenticate"),
        KbUsage("unavailable"): ("KB · unavailable", "Knowledge base lookup failed (see echo-OS log)"),
        KbUsage("off"): ("KB off", "Knowledge base agent is turned off"),
    }
    for usage, (label, tooltip) in expected.items():
        icons, labels = _kb_status(card_with(usage))
        assert labels == [label]
        assert icons[0].toolTip() == tooltip


def test_messages_without_kb_usage_have_no_status():
    assert _kb_status(card_with(None)) == ([], [])


def test_status_label_never_overlaps_the_heading():
    card = build_card(title="November 2", subtitle="a-very-long-project-folder-name-indeed", body="Done.",
                      on_click=None, kb_usage=KbUsage("not-relevant"))
    from AppKit import NSTextField
    fields = [v for v in card.subviews() if isinstance(v, NSTextField)]
    heading = next(f for f in fields if f.stringValue().startswith("November"))
    status = next(f for f in fields if f.stringValue().startswith("KB"))
    assert heading.frame().origin.x + heading.frame().size.width <= status.frame().origin.x - 4 + 0.5


def test_heading_stays_on_one_line_with_a_long_project_name():
    from AppKit import NSTextField

    def heading_height(subtitle):
        card = build_card(title="Foxtrot", subtitle=subtitle, body="Done.", on_click=None, kb_usage=KbUsage("unavailable"))
        return next(f for f in card.subviews() if isinstance(f, NSTextField) and f.stringValue().startswith("Foxtrot")).frame().size.height

    assert heading_height("a-long-project-folder-name-that-would-wrap") == heading_height("p")
