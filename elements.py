"""One colour table for every part of the app (viewer, legend, .glb export).

Standard Jmol / CPK colours. Elements missing from the table get UNKNOWN_HEX,
a bright pink that cannot be mistaken for carbon or any real element here.
"""

UNKNOWN_HEX = "#FF1493"

JMOL_HEX = {
    "H": "FFFFFF", "He": "D9FFFF", "Li": "CC80FF", "Be": "C2FF00", "B": "FFB5B5",
    "C": "909090", "N": "3050F8", "O": "FF0D0D", "F": "90E050", "Ne": "B3E3F5",
    "Na": "AB5CF2", "Mg": "8AFF00", "Al": "BFA6A6", "Si": "F0C8A0", "P": "FF8000",
    "S": "FFFF30", "Cl": "1FF01F", "Ar": "80D1E3", "K": "8F40D4", "Ca": "3DFF00",
    "Sc": "E6E6E6", "Ti": "BFC2C7", "V": "A6A6AB", "Cr": "8A99C7", "Mn": "9C7AC7",
    "Fe": "E06633", "Co": "F090A0", "Ni": "50D050", "Cu": "C88033", "Zn": "7D80B0",
    "Ga": "C28F8F", "Ge": "668F8F", "As": "BD80E3", "Se": "FFA100", "Br": "A62929",
    "Kr": "5CB8D1", "Rb": "702EB0", "Sr": "00FF00", "Y": "94FFFF", "Zr": "94E0E0",
    "Mo": "54B5B5", "Ru": "248F8F", "Rh": "0A7D8C", "Pd": "006985", "Ag": "C0C0C0",
    "Cd": "FFD98F", "In": "A67573", "Sn": "668080", "Sb": "9E63B5", "Te": "D47A00",
    "I": "940094", "Xe": "429EB0", "Cs": "57178F", "Ba": "00C900", "La": "70D4FF",
    "W": "2194D6", "Os": "266696", "Ir": "175487", "Pt": "D0D0E0", "Au": "FFD123",
    "Hg": "B8B8D0", "Tl": "A6544D", "Pb": "575961", "Bi": "9E4FB5", "U": "008FFF",
}


def hex_color(symbol: str) -> str:
    """'#RRGGBB' for an element symbol."""
    h = JMOL_HEX.get(symbol)
    return f"#{h}" if h else UNKNOWN_HEX


def rgba_color(symbol: str):
    """(r, g, b, a) floats 0..1, as Blender expects."""
    h = hex_color(symbol).lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1,)


def colors_for(symbols):
    return {s: hex_color(s) for s in symbols}
