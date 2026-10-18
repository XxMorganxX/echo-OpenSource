from AppKit import NSApplication

from echo_os import settings
from echo_os.echo.kb_usage import KbUsage
from echo_os.echo.announcer import Announcement
from echo_os.menubar.popup import NEUTRAL, build_card, card_color, display_seconds, is_sticky, meta_text

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
        KbUsage("needs-auth"): ("KB · needs login", "Knowledge base needs login: in Claude Code run /mcp, pick your KB server, Authenticate"),
        KbUsage("unavailable"): ("KB · unavailable", "Knowledge base lookup failed (see echo-OS log)"),
        KbUsage("off"): ("KB off", "No knowledge base connected (see kb.example.json)"),
    }
    for usage, (label, tooltip) in expected.items():
        icons, labels = _kb_status(card_with(usage))
        assert labels == [label]
        assert icons[0].toolTip() == tooltip


def test_messages_without_kb_usage_have_no_status():
    assert _kb_status(card_with(None)) == ([], [])


def test_kb_status_sits_in_the_footer_right_aligned_below_the_headline():
    card = build_card(title="November", subtitle="p", body="Done.", on_click=None, kb_usage=KbUsage("not-relevant"),
                      meta="12 min · 34 tools · 2:41 PM")
    fields = _fields(card)
    body = next(f for f in fields if f.stringValue() == "Done.")
    status = next(f for f in fields if f.stringValue().startswith("KB"))
    meta = next(f for f in fields if f.stringValue().startswith("12 min"))
    assert status.frame().origin.y + status.frame().size.height <= body.frame().origin.y
    assert abs((status.frame().origin.x + status.frame().size.width) - (card.frame().size.width - 14)) < 1
    assert meta.frame().origin.x + meta.frame().size.width <= status.frame().origin.x - 4 + 0.5


def test_project_name_stays_on_one_line_and_clear_of_the_header_icons():
    long_name = "a-long-project-folder-name-that-would-wrap-onto-a-second-line"

    def project_field(subtitle):
        card = build_card(title="Foxtrot", subtitle=subtitle, body="Done.", on_click=None, voice_state="speaking",
                          questions=("Push?",), on_close=lambda: None)
        return card, next(f for f in _fields(card) if f.stringValue() == subtitle)

    card, field = project_field(long_name)
    assert field.frame().size.height == project_field("p")[1].frame().size.height
    assert field.frame().origin.x + field.frame().size.width <= _voice_indicator(card).frame().origin.x


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


def test_dismiss_button_sits_in_the_header_right_of_the_speaking_indicator():
    card = build_card(title="A", subtitle="p", body="Done.", on_click=None, questions=("Push?",),
                      voice_state="speaking", on_close=lambda: None)
    button = _buttons(card)[0]
    indicator = _voice_indicator(card)
    assert indicator.frame().origin.x + indicator.frame().size.width <= button.frame().origin.x
    assert button.frame().origin.x + button.frame().size.width <= card.frame().size.width
    body = next(f for f in _fields(card) if f.stringValue() == "Done.")
    assert button.frame().origin.y > body.frame().origin.y + body.frame().size.height - 1


def _voice_indicator(card):
    from AppKit import NSImageView
    found = [view for view in card.subviews() if isinstance(view, NSImageView) and view.toolTip() in ("Speaking", "Muted")]
    return found[0] if found else None


def test_speaking_cards_show_a_speaking_indicator():
    assert _voice_indicator(build_card(title="A", subtitle="p", body="Done.", on_click=None,
                                       voice_state="speaking")).toolTip() == "Speaking"


def test_muted_cards_say_so():
    assert _voice_indicator(build_card(title="A", subtitle="p", body="Done.", on_click=None,
                                       voice_state="muted")).toolTip() == "Muted"


def test_cards_without_a_voice_state_have_no_indicator():
    assert _voice_indicator(build_card(title="A", subtitle="p", body="Done.", on_click=None)) is None


def test_each_color_slot_has_its_own_color():
    assert card_color(0) == card_color(0)
    assert len({tuple(card_color(i).getRed_green_blue_alpha_(None, None, None, None)) for i in range(len(settings.DIRECTORY_COLORS))}) == len(settings.DIRECTORY_COLORS)


def test_messages_without_a_directory_are_neutral():
    assert card_color(None) == NEUTRAL


def test_card_is_drawn_in_its_directory_color():
    assert build_card(title="A", subtitle="p", body="Done.", on_click=None, color=2).color == card_color(2)
    assert build_card(title="CI", subtitle="", body="Done.", on_click=None).color == NEUTRAL


def test_call_sign_is_on_a_pill_with_the_project_beside_it():
    card = build_card(title="Charlie", subtitle="echo-OS", body="Done.", on_click=None)
    texts = _texts(card)
    assert "Charlie" in texts and "echo-OS" in texts


def test_meta_line_reads_length_tools_and_finish_time():
    from datetime import datetime
    finished = datetime(2026, 10, 17, 14, 41).timestamp()
    assert meta_text(duration_seconds=725, tool_calls=34, finished_at=finished) == "12 min · 34 tools · 2:41 PM"


def test_meta_line_uses_seconds_hours_and_singular_tool():
    assert meta_text(duration_seconds=45, tool_calls=1, finished_at=None) == "45 s · 1 tool"
    assert meta_text(duration_seconds=3900, tool_calls=None, finished_at=None) == "1 h 5 min"


def test_meta_line_is_empty_without_details():
    assert meta_text(duration_seconds=None, tool_calls=None, finished_at=None) == ""


def test_section_headings_have_icons():
    from AppKit import NSImageView

    def icons(card):
        found = []
        for sub in card.subviews():
            if isinstance(sub, NSImageView):
                found.append(sub)
            found.extend(icons(sub))
        return found

    card = build_card(title="A", subtitle="p", body="Done.", on_click=None, questions=("Push?",), suggestions=("Tests",))
    tips = [view.toolTip() for view in icons(card)]
    assert "Questions for you" in tips and "Suggestions" in tips
