from echo_os.menubar.popup_position import Anchor, anchor_from_drop, stack_origins

# AppKit coordinates: origin bottom-left, y grows upward. (x, y, width, height)
SCREEN = (0, 57, 1920, 1143)  # visible frame: top edge at 1200
SECOND = (1920, 0, 1440, 900)
WIDTH, MARGIN, GAP, SNAP = 340, 12, 8, 24


def origins(anchor, heights, screens=(SCREEN,)):
    return stack_origins(anchor, heights, screens=list(screens), default_screen=SCREEN,
                         width=WIDTH, margin=MARGIN, gap=GAP)


def drop(left, top, bottom, screens=(SCREEN,)):
    return anchor_from_drop(left=left, top=top, bottom=bottom, screens=list(screens), default_screen=SCREEN,
                            width=WIDTH, margin=MARGIN, snap_distance=SNAP)


def test_without_an_anchor_cards_stack_down_from_the_top_right_corner_fully_on_screen():
    assert origins(None, [100, 50]) == [(1568, 1088), (1568, 1030)]
    assert 1568 + WIDTH <= 1920


def test_a_downward_anchor_stacks_from_its_top_edge():
    assert origins(Anchor(x=200, edge=900, grows="down"), [100, 50]) == [(200, 800), (200, 742)]


def test_an_upward_anchor_stacks_from_its_bottom_edge_oldest_nearest():
    assert origins(Anchor(x=200, edge=100, grows="up"), [100, 50]) == [(200, 100), (200, 208)]


def test_an_anchor_on_a_missing_screen_falls_back_to_the_corner():
    assert origins(Anchor(x=2500, edge=500, grows="down"), [100]) == [(1568, 1088)]


def test_an_anchor_on_the_second_screen_is_used_there():
    assert origins(Anchor(x=2000, edge=800, grows="down"), [100], screens=(SCREEN, SECOND)) == [(2000, 700)]


def test_cards_are_kept_inside_the_screen():
    # Card would hang off the right edge (e.g. after a resolution change): pulled back on screen.
    assert origins(Anchor(x=1700, edge=1150, grows="down"), [100]) == [(1920 - WIDTH, 1050)]
    # Anchor too low for the first card when growing down: lifted so its bottom is on screen.
    assert origins(Anchor(x=200, edge=90, grows="down"), [100]) == [(200, 57)]


def test_dropping_near_the_default_corner_snaps_back_to_default():
    assert drop(left=1568 - 10, top=1188 + 15, bottom=1100) is None


def test_dropping_in_the_upper_half_grows_down_from_the_top():
    assert drop(left=300, top=1000, bottom=900) == Anchor(x=300, edge=1000, grows="down")


def test_dropping_in_the_lower_half_grows_up_from_the_bottom():
    assert drop(left=300, top=300, bottom=150) == Anchor(x=300, edge=150, grows="up")


def test_a_drop_partly_off_screen_is_clamped_onto_it():
    assert drop(left=-100, top=700, bottom=600) == Anchor(x=0, edge=700, grows="down")
    assert drop(left=600, top=1300, bottom=1200) == Anchor(x=600, edge=1200, grows="down")


def test_a_drop_on_the_second_screen_belongs_to_it():
    assert drop(left=2100, top=300, bottom=200, screens=(SCREEN, SECOND)) == Anchor(x=2100, edge=200, grows="up")


def test_anchors_round_trip_through_json_and_reject_junk():
    anchor = Anchor(x=300.5, edge=150, grows="up")
    assert Anchor.from_dict(anchor.to_dict()) == anchor
    for junk in (None, {}, {"x": 1, "edge": 2, "grows": "sideways"}, {"x": "a", "edge": 2, "grows": "up"}, [1, 2]):
        assert Anchor.from_dict(junk) is None
