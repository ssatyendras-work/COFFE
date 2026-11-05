# Co-Nexus: convert a legacy COFFE key=value input (input_files/*.txt) to the YAML COFFE2 reads, with COFFE's own
# legacy parser (coffe.utils.load_arch_params), so the values are exactly what the archived runs used.
#   python conexus/legacy_input.py input_files/flut0.txt conexus/inputs/flut0.yaml
# model_path is written relative to the COFFE checkout (spice_models/...); conexus/run_experiment.py resolves it.

import inspect
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coffe.utils as utils


def convert(source, target):
    """ Write target (YAML) from source (legacy text); returns the parameters. """

    params = utils.load_arch_params(source)
    # Only what COFFE2's YAML loader accepts (the keys of its defaults in load_params); the legacy parser also returns
    # bookkeeping such as hb_files, which the YAML loader rejects.
    known = set(re.findall(r"^\s+'(\w+)'\s*:", inspect.getsource(utils.load_params), re.M))
    params = {k: v for k, v in params.items() if k in known}
    params["model_path"] = os.path.join("spice_models", os.path.basename(params["model_path"]))
    params["metal"] = [list(layer) for layer in params["metal"]]
    params.pop("arch_out_folder", None)
    header = "# Converted from %s by conexus/legacy_input.py (COFFE's legacy parser); do not edit.\n" % source
    with open(target, "w") as handle:
        handle.write(header + yaml.safe_dump({"fpga_arch_params": params}, sort_keys=False))
    return params


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
