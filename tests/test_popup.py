from AppKit import NSApplication

from echo_os import settings
from echo_os.echo.kb_usage import KbUsage
from echo_os.echo.announcer import Announcement
from echo_os.menubar.popup import build_card, display_seconds, is_sticky

# Controls only dispatch their actions once an NSApplication exists, as it always does in the app.
NSApplication.sharedApplication()


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


def _fields(view):
    """All text fields in drawing order, including those nested in bullet rows."""
    from AppKit import NSTextField
    found = []
    for sub in view.subviews():
        if isinstance(sub, NSTextField):
            found.append(sub)
        found.extend(_fields(sub))
    return found


def _texts(card):
    return [f.stringValue() for f in _fields(card)]


def test_questions_and_suggestions_are_bulleted_under_the_headline():
    card = build_card(title="A", subtitle="p", body="Done, with questions on screen.", on_click=None,
                      questions=("Push to main?", "Which voice?"), suggestions=("Add a test set",))
    texts = _texts(card)
    assert "Questions for you" in texts and "Suggestions" in texts
    assert "Push to main?" in texts and "Which voice?" in texts and "Add a test set" in texts
    assert texts.count("•") == 3
    assert texts.index("Questions for you") < texts.index("Push to main?") < texts.index("Suggestions")


def test_every_line_of_a_wrapped_item_fits_its_frame():
    """Regression: a two-line question was measured as one line and its last words were cut off."""
    item = "Should I build the 15-turn test set and the pre-run?"
    card = build_card(title="Bravo", subtitle="echo-OS", body="Done.", on_click=None, questions=(item,))
    field = next(f for f in _fields(card) if f.stringValue() == item)
    needed = field.cell().cellSizeForBounds_(((0, 0), (field.frame().size.width, 10_000))).height
    assert field.frame().size.height >= needed


def test_wrapped_items_hang_under_their_text_not_the_bullet():
    item = "Test lower effort on about 15 recent long turns before changing the default."
    card = build_card(title="A", subtitle="p", body="Done.", on_click=None, suggestions=(item,))
    fields = _fields(card)
    bullet = next(f for f in fields if f.stringValue() == "•")
    text = next(f for f in fields if f.stringValue() == item)
    assert text.frame().origin.x > bullet.frame().origin.x + bullet.frame().size.width - 1


def test_cards_without_items_have_no_sections():
    texts = _texts(build_card(title="A", subtitle="p", body="Done.", on_click=None))
    assert "Questions for you" not in texts and "Suggestions" not in texts


def test_items_make_the_card_taller():
    plain = build_card(title="A", subtitle="p", body="Done.", on_click=None)
    with_items = build_card(title="A", subtitle="p", body="Done.", on_click=None, questions=("Push to main?",))
    assert with_items.frame().size.height > plain.frame().size.height


def _buttons(card):
    from AppKit import NSButton
    found = []
    for sub in card.subviews():
        if isinstance(sub, NSButton):
            found.append(sub)
    return found


def test_cards_with_questions_or_suggestions_are_sticky():
    plain = Announcement(spoken_text="x", title="A", subtitle="p", body="Done.")
    assert not is_sticky(plain)
    assert is_sticky(Announcement(spoken_text="x", title="A", subtitle="p", body="Done.", questions=("Push?",)))
    assert is_sticky(Announcement(spoken_text="x", title="A", subtitle="p", body="Done.", suggestions=("Add tests",)))


def test_sticky_cards_have_a_dismiss_button_and_plain_cards_do_not():
    closed = []
    sticky = build_card(title="A", subtitle="p", body="Done.", on_click=None, questions=("Push?",),
                        on_close=lambda: closed.append(True))
    button = _buttons(sticky)[0]
    assert button.toolTip() == "Dismiss"
    button.performClick_(None)
    assert closed == [True]
    assert _buttons(build_card(title="A", subtitle="p", body="Done.", on_click=None)) == []


def test_dismiss_button_sits_right_of_the_kb_status():
    card = build_card(title="A", subtitle="p", body="Done.", on_click=None, questions=("Push?",),
                      kb_usage=KbUsage("not-relevant"), on_close=lambda: None)
    button = _buttons(card)[0]
    status = next(f for f in _fields(card) if f.stringValue().startswith("KB"))
    assert status.frame().origin.x + status.frame().size.width <= button.frame().origin.x
    assert button.frame().origin.x + button.frame().size.width <= card.frame().size.width
