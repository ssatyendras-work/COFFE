# Co-Nexus: a 3-input LUT, so COFFE2 can build a fracturable 4-LUT (two 3-LUT halves and the flut mux), which
# P1's K4-F1 tiles need (X-PACE G0.4c). COFFE2 has 6-, 5- and 4-LUT generators; this one is made from its 4-LUT,
# one level shorter: two levels, the internal buffer, one level, the output buffer. Node names stay the 4-LUT's
# (level 3 ends where level 4 did, n_8_*), so its top-level deck (top_level.generate_lut4_top) measures it as is.
# Transistor and wire names are the 4-LUT's without level 4.

import os
import tempfile

import coffe.lut_subcircuits as lut_subcircuits


def _from_lut4(generate_lut4, spice_filename, min_tran_width, use_finfet):
    """ The 4-LUT generator's text, one level shorter, appended to spice_filename; its names without level 4. """

    handle, scratch = tempfile.mkstemp(suffix=".l")
    os.close(handle)
    try:
        tran_names, wire_names = generate_lut4(scratch, min_tran_width, use_finfet)
        with open(scratch) as source:
            text = source.read()
    finally:
        os.remove(scratch)
    lines = []
    for line in text.splitlines(True):
        if "lut_L4" in line:
            continue  # level 4: its switches and wires
        if "lut_L3" in line:
            line = line.replace("n_7_1", "n_8_1").replace("n_7_2", "n_8_2").replace("n_7_3", "n_8_3")
        lines.append(line.replace("4-LUT", "3-LUT").replace("4LUT", "3LUT").replace("a 4-LUT", "a 3-LUT"))
    with open(spice_filename, "a") as target:
        target.write("".join(lines))
    return [n for n in tran_names if "lut_L4" not in n], [n for n in wire_names if "lut_L4" not in n]


def generate_ptran_lut3(spice_filename, min_tran_width, use_finfet):
    """ A 3-LUT with pass transistors; returns its transistor and wire names. """

    return _from_lut4(lut_subcircuits.generate_ptran_lut4, spice_filename, min_tran_width, use_finfet)


def generate_tgate_lut3(spice_filename, min_tran_width, use_finfet):
    """ A 3-LUT with transmission gates; returns its transistor and wire names. """

    return _from_lut4(lut_subcircuits.generate_tgate_lut4, spice_filename, min_tran_width, use_finfet)
