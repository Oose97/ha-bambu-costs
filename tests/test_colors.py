"""Bambu's colour palette lookup, keyed by material, product line and hex."""

from custom_components.bambu_costs.colors import (
    COLOR_NAMES_BY_LINE,
    LEGACY_COLOR_NAMES,
    UNKNOWN_COLOR,
    color_name,
)


def test_the_line_picks_the_code():
    # One hex, one material — a different code per product line.
    assert color_name("#FFFFFF", "PLA", "Bambu PLA Basic") == "Jade White (10100)"
    assert color_name("#FFFFFF", "PLA", "Bambu PLA Matte") == "Ivory White (11100)"
    assert color_name("#FFFFFF", "PLA", "Bambu PLA Pure") == "Pure White (17100)"
    # Longest line name wins: Silk+ is not Silk.
    assert color_name("#FFFFFF", "PLA", "Bambu PLA Silk+") == "White (13110)"
    assert color_name("#FFFFFF", "PLA", "Bambu PLA Silk") == "White (13105)"


def test_material_picks_the_right_tables():
    assert color_name("#00AE42", "PLA") == "Bambu Green (10501)"
    assert color_name("#00AE42", "ABS") == "Bambu Green (40500)"
    assert color_name("#FFFFFF", "PETG", "SUNLU PETG HF") == "White (33100)"


def test_no_hints_prefers_pla_basic():
    assert color_name("#00AE42") == "Bambu Green (10501)"
    assert color_name("#f7e6de") == "Beige (10201)", "case-insensitive"


def test_duplicate_codes_prefer_the_plain_colour():
    # PETG Basic carries both Translucent (30103) and White (30106) on this
    # hex; an opaque white spool should not be called Translucent.
    assert color_name("#FFFFFF", "PETG", "SUNLU PETG Basic") == "White (30106)"


def test_parenthesised_line_matches_by_either_half():
    assert color_name("#000000", "TPU", "Bambu TPU for AMS") == "Black (53101)"
    assert color_name("#000000", "TPU", "Bambu TPU 95A HF") == "Black (51100)"


def test_compound_material_matches_its_family():
    assert color_name("#000000", "PLA-CF", "Bambu PLA-CF") == "Black (14100)"
    assert color_name("#000000", "PA6-GF") == "Black (72100)"


def test_material_without_the_hex_borrows_a_siblings_name():
    # ASA has no #FEC600; the colour is still better named than dropped.
    assert color_name("#FEC600", "ASA") == "Sunflower Yellow (10402)"


def test_gradient_hexes_each_name_their_filament():
    assert color_name("#54FF9B") == "Ocean to Meadow (10902)"
    assert color_name("#307FE2") == "Ocean to Meadow (10902)"


def test_unknown_hex_is_not_an_error():
    assert color_name("#123456") == UNKNOWN_COLOR
    assert color_name(None) == UNKNOWN_COLOR
    assert color_name("") == UNKNOWN_COLOR
    assert color_name("#123456", "PLA", "Bambu PLA Basic") == UNKNOWN_COLOR


def test_palette_keys_are_normalised():
    for lines in COLOR_NAMES_BY_LINE.values():
        for hexes in lines.values():
            for key in hexes:
                assert key.startswith("#") and len(key) == 7 and key == key.upper()
    for key in LEGACY_COLOR_NAMES:
        assert key.startswith("#") and len(key) == 7 and key == key.upper()
