"""Bambu's colour palette lookup, keyed by material and hex."""

from custom_components.bambu_costs.colors import (
    COLOR_NAMES_BY_MATERIAL,
    LEGACY_COLOR_NAMES,
    UNKNOWN_COLOR,
    color_name,
)


def test_material_picks_the_right_code():
    # Same hex, same colour, different filament code per material.
    assert color_name("#00AE42", "PLA") == "Bambu Green (10501)"
    assert color_name("#00AE42", "ABS") == "Bambu Green (40500)"
    assert color_name("#00AE42", "PETG") == "Green (33500)"


def test_no_material_prefers_pla():
    assert color_name("#00AE42") == "Bambu Green (10501)"
    assert color_name("#f7e6de") == "Beige (10201)", "case-insensitive"


def test_compound_material_matches_its_family():
    # Trays report compounds like PLA-CF; the family prefix picks the table.
    assert color_name("#00AE42", "PLA-CF") == "Bambu Green (10501)"
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
    assert color_name("#123456", "PLA") == UNKNOWN_COLOR


def test_palette_keys_are_normalised():
    for hexes in COLOR_NAMES_BY_MATERIAL.values():
        for key in hexes:
            assert key.startswith("#") and len(key) == 7 and key == key.upper()
    for key in LEGACY_COLOR_NAMES:
        assert key.startswith("#") and len(key) == 7 and key == key.upper()
