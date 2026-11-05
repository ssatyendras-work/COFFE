# Co-Nexus: one timed COFFE2 experiment, the same on the ThinkPad, Hyperion (Docker) and the Slurm cluster (udocker),
# with HSPICE or ngspice. Plain Python 3 with COFFE's own dependencies; nothing of Co-Nexus is needed for HSPICE.
#
#   python conexus/run_experiment.py --coffe-root <COFFE checkout> --input conexus/inputs/flut0.yaml --tier A --out <dir>
#
# Tier A (minutes): COFFE without sizing (-n), then sb_mux at its initial sizes and as a 2-point sweep
# (conexus/subcircuit_probe.py). Tier B (hours): COFFE's full sizing (-i ITERATIONS, the archived flut0 run used 4).
# The simulator is COFFE_SIMULATOR (hspice: released COFFE2 at --coffe-root, e.g. master at the pin; ngspice: this
# branch). <out> gets the resolved input, COFFE's output folder (arch/), report.txt, timing.json and, for ngspice,
# records.jsonl.gz (every point's record). timing.json: wall and CPU time (this process's children: COFFE and every
# simulator run), simulations, seconds per simulation, host, CPU model, CPUs allowed, and the settings.

import argparse
import gzip
import json
import os
import platform
import re
import resource
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def cpu_model():
    """ The CPU's model name from /proc/cpuinfo. """

    try:
        with open("/proc/cpuinfo") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def cpus_allowed():
    """ CPUs this process may use: the affinity mask, and the cgroup quota when one is set. """

    count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    quota = None
    try:
        with open("/sys/fs/cgroup/cpu.max") as handle:
            limit, period = handle.read().split()
            if limit != "max":
                quota = round(int(limit) / int(period), 2)
    except (OSError, ValueError):
        pass
    return {"affinity": count, "cgroup_quota": quota}


class Experiment(object):
    """ One tier of one input on one simulator, timed. """

    def __init__(self, coffe_root, source, tier, out, iterations, points):

        self.coffe_root, self.source, self.tier = os.path.abspath(coffe_root), source, tier
        self.out, self.iterations, self.points = os.path.abspath(out), iterations, points
        self.simulator = os.environ.get("COFFE_SIMULATOR", "hspice").lower()
        self.steps = []
        return


    def resolve_input(self):
        """ The input with model_path in the COFFE checkout and the output folder under <out>/arch. """

        with open(self.source) as handle:
            text = handle.read()
        text = re.sub(r"(?m)^(\s*model_path\s*:\s*)(\S+)", lambda m: m.group(1) + os.path.join(self.coffe_root, "spice_models", os.path.basename(m.group(2))), text)
        text = re.sub(r"(?m)^\s*arch_out_folder\s*:.*\n", "", text)
        text = text.replace("fpga_arch_params:\n", "fpga_arch_params:\n  arch_out_folder: %s\n" % os.path.join(self.out, "arch"), 1)
        target = os.path.join(self.out, "input.yaml")
        with open(target, "w") as handle:
            handle.write(text)
        return target


    def step(self, name, command):
        """ Run one command, its output in <out>/<name>.log; record its wall and CPU time. """

        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.time()
        with open(os.path.join(self.out, name + ".log"), "w") as log:
            code = subprocess.call(command, cwd=self.coffe_root, stdout=log, stderr=subprocess.STDOUT)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        step = {"name": name, "command": command, "exit": code, "wall_s": round(time.time() - start, 2),
                "cpu_s": round((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime), 2)}
        self.steps.append(step)
        return step


    def run(self):
        """ The tier's steps, then the report, the records and timing.json. Returns the exit status. """

        os.makedirs(self.out, exist_ok=True)
        source = self.resolve_input()
        python = sys.executable
        if self.tier == "A":
            self.step("coffe_no_sizing", [python, "-W", "ignore", "coffe.py", "-n", source])
            probe_input = source.replace("input.yaml", "probe_input.yaml")
            with open(source) as handle:
                text = handle.read().replace(os.path.join(self.out, "arch"), os.path.join(self.out, "probe"))
            with open(probe_input, "w") as handle:
                handle.write(text)
            self.step("sb_mux_probe", [python, "-W", "ignore", os.path.join(HERE, "subcircuit_probe.py"), probe_input,
                                       "--points", str(self.points), "--out", os.path.join(self.out, "sb_mux_probe.json")])
        else:
            self.step("coffe_sizing", [python, "-W", "ignore", "coffe.py", "-i", str(self.iterations), source])
        report = os.path.join(self.out, "arch", "report.txt")
        if os.path.isfile(report):
            shutil.copyfile(report, os.path.join(self.out, "report.txt"))
        self.collect_records()
        timing = self.timing(report)
        with open(os.path.join(self.out, "timing.json"), "w") as handle:
            json.dump(timing, handle, indent=1)
        print(json.dumps({k: timing[k] for k in ("tier", "simulator", "wall_s", "cpu_s", "simulations", "s_per_simulation", "host")}))
        if not os.path.isfile(report):  # COFFE exits 0 on an input it rejects
            print("no report.txt: see %s" % os.path.join(self.out, self.steps[0]["name"] + ".log"), file=sys.stderr)
            return 1
        return max(step["exit"] for step in self.steps)


    def collect_records(self):
        """ Every ngspice point record of the run, in one gzip file. """

        found = []
        for root, _, files in os.walk(self.out):
            found += [os.path.join(root, f) for f in files if f == "ngspice_runs.jsonl"]
        if found:
            with gzip.open(os.path.join(self.out, "records.jsonl.gz"), "wt") as target:
                for path in sorted(found):
                    with open(path) as handle:
                        shutil.copyfileobj(handle, target)
        return len(found)


    def timing(self, report):
        """ What timing.json holds. """

        simulations = None
        if os.path.isfile(report):
            with open(report) as handle:
                match = re.search(r"Number of HSPICE simulations performed:\s*(\d+)", handle.read())
            simulations = int(match.group(1)) if match else None
        probe = os.path.join(self.out, "sb_mux_probe.json")
        probe_data = json.load(open(probe)) if os.path.isfile(probe) else {}
        wall = sum(s["wall_s"] for s in self.steps)
        main = self.steps[0]
        return {
            "tier": self.tier, "simulator": self.simulator, "input": os.path.basename(self.source), "iterations": self.iterations if self.tier == "B" else None,
            "tmax": os.environ.get("COFFE_NGSPICE_TMAX", "5p") if self.simulator == "ngspice" else None,
            "workers": int(os.environ.get("COFFE_NGSPICE_WORKERS", "1")) if self.simulator == "ngspice" else 1,
            "wall_s": round(wall, 2), "cpu_s": round(sum(s["cpu_s"] for s in self.steps), 2),
            "simulations": simulations, "s_per_simulation": round(main["wall_s"] / simulations, 3) if simulations else None,
            "cpu_s_per_simulation": round(main["cpu_s"] / simulations, 3) if simulations else None,
            "sb_mux_s_per_point": probe_data.get("s_per_point"), "host": os.environ.get("CONEXUS_HOST") or socket.gethostname(),
            "cpu_model": cpu_model(), "cpus": cpus_allowed(), "slurm_job": os.environ.get("SLURM_JOB_ID"), "steps": self.steps,
            "coffe_root": self.coffe_root, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - wall)),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coffe-root", required=True, help="the COFFE checkout to run (released COFFE2 for HSPICE, this branch for ngspice)")
    parser.add_argument("--input", required=True, help="a COFFE2 YAML input, e.g. conexus/inputs/flut0.yaml")
    parser.add_argument("--tier", choices=["A", "B"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--iterations", type=int, default=4, help="tier B sizing iterations (the archived flut0 run: 4)")
    parser.add_argument("--points", type=int, default=2, help="tier A sb_mux sweep points")
    a = parser.parse_args()
    sys.exit(Experiment(a.coffe_root, a.input, a.tier, a.out, a.iterations, a.points).run())


if __name__ == "__main__":
    main()
