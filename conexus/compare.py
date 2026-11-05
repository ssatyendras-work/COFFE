# Co-Nexus: compare COFFE2 runs (conexus/run_experiment.py output folders) with an archived report, and their timing.
# Standard library only, so it runs anywhere a kit's results come back to.
#
#   python conexus/compare.py <result dir> [<result dir> ...] \
#       --archive unit_tests/test_results_archive/custom_flow_results/flut_report.txt [--markdown comparison.md]
#
# Prints, and with --markdown writes: a timing table (one row per run: simulator, max step, workers, host, CPU, wall
# and CPU time, simulations, seconds per simulation) and, for every run with a report, its tile area, representative
# critical path and per-subcircuit delays and areas against the archive, as % differences.

import argparse
import json
import os
import re


class CoffeReport(object):
    """ The numbers of a COFFE report.txt: per-subcircuit area, delay, fall, rise and power; tile area; critical path. """

    ROW = re.compile(r"^\s{2}(\S+(?: \(with sram\)|\(with sram\))?)\s+(n/a|[-\d.e]+)\s+(n/a|[-\d.e]+)\s+(n/a|[-\d.e]+)\s+(n/a|[-\d.e]+)\s+(n/a|[-\d.e]+)\s*$")

    def __init__(self, path):

        self.path = path
        with open(path) as handle:
            self.text = handle.read()
        self.subcircuits = {}
        table = self.text.split("SUBCIRCUIT AREA, DELAY & POWER", 1)[-1].split("TILE AREA CONTRIBUTIONS", 1)[0]
        for line in table.splitlines():
            match = self.ROW.match(line)
            if match:
                values = [None if v == "n/a" else float(v) for v in match.groups()[1:]]
                self.subcircuits[match.group(1).replace(" (with sram)", "(with sram)")] = dict(zip(("area", "delay", "tfall", "trise", "power"), values))
        self.tile_area = self._number(r"Tile Area\s+([\d.]+) um\^2")
        self.critical_path = self._number(r"Representative Critical Path Delay\s+([\d.]+) ps")
        self.simulations = self._number(r"Number of HSPICE simulations performed:\s*(\d+)")
        return


    def _number(self, pattern):
        match = re.search(pattern, self.text)
        return float(match.group(1)) if match else None


def percent(value, reference):
    """ (value - reference) / reference in %, or None. """

    if value is None or not reference:
        return None
    return 100.0 * (value - reference) / reference


def fmt(value, digits=1):
    return "-" if value is None else ("%+.*f" % (digits, value))


class Comparison(object):
    """ Runs against an archived report, and their timing. """

    def __init__(self, runs, archive):

        self.runs = [os.path.abspath(r) for r in runs]
        self.archive = CoffeReport(archive) if archive else None
        return


    def timing(self, run):
        path = os.path.join(run, "timing.json")
        return json.load(open(path)) if os.path.isfile(path) else {}


    def label(self, run):
        t = self.timing(run)
        return "%s %s%s tier %s" % (os.path.basename(run), t.get("simulator", "?"), (" " + t["tmax"]) if t.get("tmax") else "", t.get("tier", "?"))


    def timing_table(self):
        lines = ["| run | simulator | max step | workers | host | CPU | wall (h) | CPU (h) | simulations | s per simulation | sb_mux s per point |",
                 "|---|---|---|---|---|---|---|---|---|---|---|"]
        for run in self.runs:
            t = self.timing(run)
            if not t:
                lines.append("| %s | no timing.json | | | | | | | | | |" % os.path.basename(run))
                continue
            lines.append("| %s | %s | %s | %s | %s | %s | %.2f | %.2f | %s | %s | %s |" % (
                os.path.basename(run), t["simulator"], t.get("tmax") or "-", t.get("workers"), t.get("host"), t.get("cpu_model"),
                t["wall_s"] / 3600, t["cpu_s"] / 3600, t.get("simulations") or "-", t.get("s_per_simulation") or "-", t.get("sb_mux_s_per_point") or "-"))
        return "\n".join(lines)


    def accuracy_tables(self):
        if self.archive is None:
            return ""
        out = []
        for run in self.runs:
            path = os.path.join(run, "report.txt")
            if not os.path.isfile(path):
                out.append("### %s\n\nno report.txt" % self.label(run))
                continue
            report = CoffeReport(path)
            out.append("### %s\n" % self.label(run))
            out.append("| | archive (HSPICE) | this run | difference |\n|---|---|---|---|")
            out.append("| tile area (um2) | %.2f | %s | %s %% |" % (self.archive.tile_area, report.tile_area, fmt(percent(report.tile_area, self.archive.tile_area))))
            out.append("| critical path (ps) | %.2f | %s | %s %% |" % (self.archive.critical_path, report.critical_path, fmt(percent(report.critical_path, self.archive.critical_path))))
            out.append("| simulations | %d | %s | |\n" % (self.archive.simulations, int(report.simulations) if report.simulations else "-"))
            out.append("| subcircuit | delay archive (ps) | delay run | delay diff % | area archive (um2) | area run | area diff % |\n|---|---|---|---|---|---|---|")
            for name, ref in self.archive.subcircuits.items():
                mine = report.subcircuits.get(name, {})
                out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                    name, ref["delay"] if ref["delay"] is not None else "-", mine.get("delay", "-") if mine.get("delay") is not None else "-",
                    fmt(percent(mine.get("delay"), ref["delay"])), ref["area"] if ref["area"] is not None else "-",
                    mine.get("area", "-") if mine.get("area") is not None else "-", fmt(percent(mine.get("area"), ref["area"]))))
            delays = [abs(percent(report.subcircuits[n]["delay"], r["delay"])) for n, r in self.archive.subcircuits.items()
                      if r["delay"] and report.subcircuits.get(n, {}).get("delay") is not None]
            if delays:
                out.append("\nMean |delay difference| over %d subcircuits: %.1f %%; largest %.1f %%.\n" % (len(delays), sum(delays) / len(delays), max(delays)))
        return "\n".join(out)


    def markdown(self):
        head = "# COFFE2 runs against %s\n\n## Timing\n\n" % (os.path.basename(self.archive.path) if self.archive else "no archive")
        return head + self.timing_table() + "\n\n## Accuracy\n\n" + self.accuracy_tables() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--archive", default=None)
    parser.add_argument("--markdown", default=None)
    a = parser.parse_args()
    text = Comparison(a.runs, a.archive).markdown()
    print(text)
    if a.markdown:
        with open(a.markdown, "w") as handle:
            handle.write(text)


if __name__ == "__main__":
    main()
