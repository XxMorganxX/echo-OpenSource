from echo_os import settings
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
