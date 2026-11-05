# Co-Nexus: run one COFFE subcircuit on the configured SPICE interface, at COFFE's initial sizes and
# then as a sizing sweep, and time it per point (an estimate of a tile's sizing time on ngspice).
#   python conexus/subcircuit_probe.py <input.yaml> [--subcircuit sb_mux] [--points 8] [--out probe.json]
# Generates the tile's SPICE files like coffe.py (no sizing), then runs only the named subcircuit.

import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coffe.fpga as fpga
import coffe.ngspice_interface as ngspice_interface
import coffe.utils as utils


def coffe_args(arch_description):
    """ The argument namespace coffe.py builds, at its defaults with no sizing. """

    return argparse.Namespace(arch_description=arch_description, no_sizing=True, opt_type="global", initial_sizes="default", re_erf=1,
                              area_opt_weight=1, delay_opt_weight=1, max_iterations=6, size_hb_interfaces=0.0, hardblock_only=False,
                              gen_hb_scripts=False, parallel_hb_flow=False, parse_pll_hb_flow=False, quick_mode=-1.0)


def parameter_dict(fpga_inst):
    """ Current transistor sizes and wire RC as update_delays builds them (one point). """

    params = {}
    for name, size in fpga_inst.transistor_sizes.items():
        params[name] = [size if fpga_inst.specs.use_finfet else 1e-9 * size * fpga_inst.specs.min_tran_width]
    for name, (res, cap) in fpga_inst.wire_rc_dict.items():
        params[name + "_res"] = [res]
        params[name + "_cap"] = [cap * 1e-15]
    return params


def sweep(params, names, points):
    """ A sizing-like sweep: the named transistors scaled from 1x to 2x over the points, the rest fixed. """

    swept = {}
    for name, (value,) in params.items():
        swept[name] = [value * (1 + i / max(1, points - 1)) if name in names else value for i in range(points)]
    return swept


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arch_description")
    parser.add_argument("--subcircuit", default="sb_mux")
    parser.add_argument("--points", type=int, default=8)
    parser.add_argument("--out", default="probe.json")
    a = parser.parse_args()
    args = coffe_args(a.arch_description)
    params = utils.load_params(args.arch_description, args)
    folder = utils.create_output_dir(args.arch_description, params["fpga_arch_params"]["arch_out_folder"])
    interface = ngspice_interface.make_interface()
    fpga_inst = fpga.FPGA(params, args, interface)
    os.chdir(folder)
    fpga_inst.generate(False, False)
    # As coffe.py does without sizing: area, then wire lengths and RC from it, before any simulation.
    fpga_inst.lb_height = math.sqrt(fpga_inst.area_dict["tile"])
    fpga_inst.update_area()
    fpga_inst.compute_distance()
    fpga_inst.update_wires()
    fpga_inst.update_wire_rc()
    circuit = getattr(fpga_inst, a.subcircuit)
    base = parameter_dict(fpga_inst)
    start = time.time()
    single = interface.run(circuit.top_spice_path, base)
    single_s = time.time() - start
    names = [n for n in base if a.subcircuit in n and not n.startswith("wire")]
    start = time.time()
    swept = interface.run(circuit.top_spice_path, sweep(base, names, a.points))
    sweep_s = time.time() - start
    result = {
        "input": a.arch_description, "subcircuit": a.subcircuit, "simulator": os.environ.get("COFFE_SIMULATOR", "hspice"),
        "use_tgate": params["fpga_arch_params"]["use_tgate"], "single": single, "single_s": round(single_s, 2),
        "swept_transistors": names, "points": a.points, "sweep": swept, "sweep_s": round(sweep_s, 2), "s_per_point": round(sweep_s / a.points, 2),
    }
    with open(a.out, "w") as handle:
        json.dump(result, handle, indent=1)
    print(json.dumps({k: result[k] for k in ("subcircuit", "use_tgate", "single_s", "points", "sweep_s", "s_per_point")}))
    print({k: v for k, v in single.items() if k.startswith("meas_total") or k == "meas_avg_power"})


if __name__ == "__main__":
    main()
