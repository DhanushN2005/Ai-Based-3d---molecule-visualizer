from elements import UNKNOWN_HEX, colors_for, hex_color, rgba_color


def test_common_elements_have_standard_colours():
    assert hex_color("C") == "#909090"
    assert hex_color("O") == "#FF0D0D"
    assert hex_color("N") == "#3050F8"
    assert hex_color("H") == "#FFFFFF"


def test_unknown_element_is_bright_pink_not_carbon_grey():
    assert hex_color("Xx") == UNKNOWN_HEX
    assert UNKNOWN_HEX != hex_color("C")


def test_rgba_is_blender_style_floats():
    r, g, b, a = rgba_color("O")
    assert (r, a) == (1.0, 1)
    assert 0 <= g < 0.1 and 0 <= b < 0.1


def test_colors_for_maps_every_symbol():
    assert colors_for(["C", "Zz"]) == {"C": "#909090", "Zz": UNKNOWN_HEX}
