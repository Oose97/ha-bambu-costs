"""Bambu's colour palette lookup."""

from custom_components.bambu_costs.colors import COLOR_NAMES, UNKNOWN_COLOR, color_name


def test_known_hex_resolves():
    assert color_name("#00AE42") == "Bambu Green (10501)"
    assert color_name("#f7e6de") == "Beige (10201)", "case-insensitive"


def test_unknown_hex_is_not_an_error():
    assert color_name("#123456") == UNKNOWN_COLOR
    assert color_name(None) == UNKNOWN_COLOR
    assert color_name("") == UNKNOWN_COLOR


def test_palette_keys_are_normalised():
    for key in COLOR_NAMES:
        assert key.startswith("#") and len(key) == 7 and key == key.upper()
