# Co-Nexus: tests of the ngspice port (coffe/ngspice_interface.py, coffe/ngspice_dialect.py).
# They need conexus_hatf_tech (HATF-TECH-M0.3) importable and no simulator: a fake ngspice
# prints the measures. Run from the repository root: python -m pytest tests/test_conexus_ngspice.py

import json
import os
import stat
import textwrap

import pytest

import coffe.ngspice_dialect as dialect
import coffe.spice as spice

LIBRARY = textwrap.dedent("""\
    .LIB BASIC_SUBCIRCUITS
    .SUBCKT wire n_in n_out Rw=1 Cw=1
    CWIRE_1 n_in gnd Cw
    RWIRE_1 n_in n_out Rw
    CWIRE_2 n_out gnd Cw
    .ENDS
    .SUBCKT inv n_in n_out n_vdd n_gnd Wn=45n Wp=45n
    MN n_out n_in n_gnd n_gnd nmos L=gate_length W=Wn
    .ENDS
    .SUBCKT stage n_in n_out n_vdd n_gnd
    Xinv_1 n_in n_mid n_vdd n_gnd inv Wn=inv_1_nmos Wp=inv_1_pmos
    Xwire n_mid n_out wire Rw=wire_res Cw=wire_cap
    .ENDS
    .SUBCKT load n_in n_out n_vdd n_gnd
    Xstage_on n_in n_x n_vdd n_gnd stage
    Rx n_x n_out 1
    .ENDS
    .ENDL BASIC_SUBCIRCUITS
    """)

DECK = textwrap.dedent("""\
    .TITLE test
    .LIB "../includes.l" INCLUDES
    .TRAN 1p 4n SWEEP DATA=sweep_data
    .MEASURE TRAN meas_total_tfall TRIG V(Xload_1.Xstage_on.n_in) VAL='supply_v/2' FALL=1
    +    TARG V(Xload_1.Xstage_on.Xinv_1.n_out) VAL='supply_v/2' RISE=1
    .MEASURE TRAN meaz1_delay TRIG V(n_in) VAL=0.4 RISE=1 TARG V(Xload_1.n_out) VAL=0.4 RISE=1
    .MEASURE TRAN meaz2_delay TRIG V(n_in) VAL=0.4 RISE=1 TARG V(Xload_1.Xstage_on.n_gnd) VAL=0.4 RISE=1
    .MEASURE TRAN meas_current INTEGRAL I(V_TEST) FROM=0ns TO=4ns
    VIN n_in gnd PULSE (supply_v 0 0 0 0 2n 4n)
    Xload_1 n_1 n_2 vdd gnd load
    .END
    """)

INCLUDES = '.LIB INCLUDES\n.LIB "basic_subcircuits.l" BASIC_SUBCIRCUITS\n.INCLUDE "sweep_data.l"\n.ENDL INCLUDES\n'


@pytest.fixture
def arch(tmp_path):
    (tmp_path / "basic_subcircuits.l").write_text(LIBRARY)
    (tmp_path / "includes.l").write_text(INCLUDES)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test.sp").write_text(DECK)
    return tmp_path


def test_bare_rc_parameters_get_braces():
    text, count = dialect.translate_library(LIBRARY)
    assert count == 3 and "CWIRE_1 n_in gnd {Cw}" in text and "RWIRE_1 n_in n_out {Rw}" in text
    assert "Rx n_x n_out 1" in text  # numbers stay


def test_source_parameters_get_braces():
    text, count = dialect.brace_source_params("vin_gate n_in_gate 0 pulse (supply_v 0 3n 0 0 2n 4n)\nVX a b PWL (0 0 1n 'supply_v/2')\n")
    assert count == 1 and "pulse ({supply_v} 0 3n 0 0 2n 4n)" in text and "'supply_v/2'" in text


def test_tran_gets_a_maximum_step():
    assert dialect.tran_tmax(".TRAN 1p 8n\n.TRAN 1p 8n 0 2p\n", "5p") == (".TRAN 1p 8n 0 5p\n.TRAN 1p 8n 0 2p\n", 1)
    assert dialect.tran_tmax(".TRAN 1p 8n\n", "")[1] == 0  # COFFE_NGSPICE_TMAX= turns it off


def test_a_find_of_ground_is_zero():
    text, count = dialect.ground_find(".MEASURE TRAN meas_logic_low_voltage FIND V(gnd) AT=3n\n.MEASURE TRAN m FIND V(n_1) AT=3n\n")
    assert count == 1 and ".MEASURE TRAN meas_logic_low_voltage PARAM='0'" in text and "FIND V(n_1)" in text


def test_port_probes_resolve_to_the_owning_net():
    hierarchy = dialect.Hierarchy([LIBRARY, DECK])
    assert hierarchy.resolve("Xload_1.Xstage_on.n_in") == "n_1"  # port of stage, port of load, top net
    assert hierarchy.resolve("Xload_1.Xstage_on.Xinv_1.n_out") == "xload_1.xstage_on.n_mid"  # port of inv, internal net of stage
    assert hierarchy.resolve("Xload_1.n_out") == "n_2"
    assert hierarchy.resolve("Xload_1.Xstage_on.n_gnd") == "0"
    assert hierarchy.resolve("Xload_1.Xstage_on.Xwire.n_mid") == "xload_1.xstage_on.xwire.n_mid"  # unknown port: left as written
    assert hierarchy.resolve("Xnone.n_in") == "xnone.n_in"


def test_the_deck_points_at_ngspice_copies_with_rules_counted(arch):
    libraries = dialect.CoffeLibraries(str(arch / "includes.l"))
    text, rules = libraries.deck_for_ngspice(DECK)
    assert dict(rules) == {"ngspice_includes": 1, "bare_rc_param": 3, "source_param": 1, "port_probe": 4, "tran_tmax": 1, "ground_find": 0}
    assert ".TRAN 1p 4n 0 5p SWEEP DATA=sweep_data" in text
    assert "PULSE ({supply_v} 0 0 0 0 2n 4n)" in text
    assert '.LIB "../includes.ngspice.l" INCLUDES' in text and "TRIG V(n_1)" in text
    assert '"basic_subcircuits.ngspice.l"' in (arch / "includes.ngspice.l").read_text()
    assert "{Cw}" in (arch / "basic_subcircuits.ngspice.l").read_text()
    assert (arch / "basic_subcircuits.l").read_text() == LIBRARY  # originals untouched


def test_meaz_combination_is_the_same_for_both_simulators():
    measured = {"meaz1_delay": ["1e-11"], "meaz2_delay": ["2e-11"], "meas_x": ["3"]}
    combined = spice.combine_meaz(dict(measured), list(measured))
    assert combined["meas_delay"] == ["2e-11"] and combined["meas_x"] == ["3"]


FAKE_NGSPICE = """#!/bin/sh
# Prints measures as ngspice does; the delay follows the swept nmos width. Each run is counted in ../../../runs.txt.
w=$(sed -n 's/^.PARAM inv_1_nmos = //p' sweep_point.l)
echo "$w" >> ../../../runs.txt
grep -q 'includes.ngspice.points.l' "$2" || echo "meas_total_tfall: wrong includes"
grep -q '^.INCLUDE "sweep_point.l"' "$2" || echo "meas_total_tfall: no point include"
grep -q '^set num_threads=1$' .spiceinit || echo "meas_total_tfall: threads not pinned"
echo "Note: Compatibility modes selected: hs a"
echo "meas_total_tfall    =  $w targ=  1e-9 trig=  1e-9"
echo "meaz1_delay         =  1.0e-11"
echo "meaz2_delay         =  2.0e-11"
echo "Error: measure  meas_current  : no such vector"
"""


def _fake(arch):
    fake = arch / "ngspice"
    fake.write_text(FAKE_NGSPICE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(fake)


def test_ngspice_runs_each_point_in_its_folder_in_parallel_and_returns_coffe_measures(arch, monkeypatch):
    pytest.importorskip("conexus_hatf_tech.simulators.decks")
    import coffe.ngspice_interface as ngspice_interface

    monkeypatch.chdir(arch)  # COFFE runs from the architecture folder
    interface = ngspice_interface.NgspiceInterface(executable=_fake(arch), osdi_path="", workers=2)
    sweep = {"inv_1_nmos": ["4.5e-08", "9e-08"], "inv_1_pmos": ["9e-08", "9e-08"]}
    measured = interface.run(str(arch / "test" / "test.sp"), sweep)
    assert measured["meas_total_tfall"] == ["4.5e-08", "9e-08"]  # in point order, whatever finished first
    assert measured["meas_current"] == ["failed", "failed"] and measured["meas_delay"] == ["2.0e-11", "2.0e-11"]
    assert interface.get_num_simulations_performed() == 2
    records = [json.loads(line) for line in (arch / "test" / "ngspice_runs.jsonl").read_text().splitlines()]
    assert len(records) == 2 and {"rule": "port_probe", "count": 4} in records[0]["coffe_rules"] and records[0]["status"]["meas_current"] == "failed"
    folders = sorted((arch / "test" / "points").iterdir())
    assert [f.name for f in folders] == ["test." + r["point_id"] for r in records]
    assert [p.name for p in folders[0].iterdir()] == ["record.json"]  # deck and log not kept by default
    assert "set ngbehavior=hsa" not in (arch / "includes.ngspice.points.l").read_text() and "sweep_data.l" not in (arch / "includes.ngspice.points.l").read_text()


def test_a_stopped_sweep_resumes_by_point_id(arch, monkeypatch):
    pytest.importorskip("conexus_hatf_tech.simulators.decks")
    import coffe.ngspice_interface as ngspice_interface

    monkeypatch.chdir(arch)
    interface = ngspice_interface.NgspiceInterface(executable=_fake(arch), osdi_path="", workers=2)
    interface.run(str(arch / "test" / "test.sp"), {"inv_1_nmos": ["4.5e-08"], "inv_1_pmos": ["9e-08"]})
    measured = interface.run(str(arch / "test" / "test.sp"), {"inv_1_nmos": ["4.5e-08", "9e-08"], "inv_1_pmos": ["9e-08", "9e-08"]})
    assert measured["meas_total_tfall"] == ["4.5e-08", "9e-08"]
    assert (arch / "runs.txt").read_text().split() == ["4.5e-08", "9e-08"]  # point 0 was not run again
    last = [json.loads(line) for line in (arch / "test" / "ngspice_runs.jsonl").read_text().splitlines()][-2:]
    assert [r["resumed"] for r in last] == [True, False]
    (arch / "test" / "test.sp").write_text(DECK.replace("2n 4n", "2n 5n"))  # another deck: no reuse
    interface.run(str(arch / "test" / "test.sp"), {"inv_1_nmos": ["4.5e-08"], "inv_1_pmos": ["9e-08"]})
    assert (arch / "runs.txt").read_text().split() == ["4.5e-08", "9e-08", "4.5e-08"]
    (arch / "basic_subcircuits.l").write_text(LIBRARY.replace("Rx n_x n_out 1", "Rx n_x n_out 2"))  # another library: no reuse
    interface.run(str(arch / "test" / "test.sp"), {"inv_1_nmos": ["4.5e-08"], "inv_1_pmos": ["9e-08"]})
    assert len((arch / "runs.txt").read_text().split()) == 4


def test_points_can_live_outside_coffes_output_folder(arch, monkeypatch, tmp_path):
    pytest.importorskip("conexus_hatf_tech.simulators.decks")
    import coffe.ngspice_interface as ngspice_interface

    monkeypatch.chdir(arch)
    monkeypatch.setenv("COFFE_NGSPICE_POINTS", str(tmp_path / "cache"))
    interface = ngspice_interface.NgspiceInterface(executable=_fake(arch), osdi_path="")
    interface.run(str(arch / "test" / "test.sp"), {"inv_1_nmos": ["4.5e-08"], "inv_1_pmos": ["9e-08"]})
    assert len(list((tmp_path / "cache" / "test").glob("test.0000-*/record.json"))) == 1 and not (arch / "test" / "points").exists()


def test_the_simulator_is_chosen_by_the_environment(monkeypatch):
    import coffe.ngspice_interface as ngspice_interface

    monkeypatch.delenv("COFFE_SIMULATOR", raising=False)
    assert type(ngspice_interface.make_interface()) is spice.SpiceInterface
    monkeypatch.setenv("COFFE_SIMULATOR", "spectre")
    with pytest.raises(ValueError):
        ngspice_interface.make_interface()
