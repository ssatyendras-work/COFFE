# Co-Nexus: an ngspice interface for COFFE, with the same run() contract as SpiceInterface.
#
# COFFE writes HSPICE decks that sweep transistor sizes with ".TRAN ... SWEEP DATA=sweep_data"
# and read the .DATA table from sweep_data.l (included by includes.l in the architecture folder).
# ngspice has no .DATA sweeps, so this interface runs one deck per sweep point: the point's
# values go into sweep_data.l as .PARAM lines, and the deck is translated by the hatf-tech
# foreign-deck rules (drop SWEEP DATA, INTEGRAL -> INTEG) and run with "set ngbehavior=hsa".
# Deck preparation and measure parsing are hatf-tech's (conexus_hatf_tech.simulators.decks,
# HATF-TECH-M0.3); this file only drives the runs and keeps COFFE's return format:
#
#   {meas_name: [value-or-"failed" per point]}
#
# with COFFE's meaz1/meaz2/meaz3 combination (spice.combine_meaz).
#
# Select it with COFFE_SIMULATOR=ngspice (coffe.py). Each point runs in its own folder,
# <deck folder>/points/<stem>.<point id>/, with its values in sweep_point.l, so points run in
# parallel (COFFE_NGSPICE_WORKERS). Its record (point id, values, rules, measure statuses and
# values, seconds) is kept there as record.json and appended to ngspice_runs.jsonl in the deck's
# folder; a point whose record.json matches the deck is not run again (resume after a stop).
# Environment:
#   COFFE_NGSPICE        ngspice executable (default: ngspice on PATH)
#   COFFE_NGSPICE_OSDI   OSDI library to load, empty for none (bulk/PTM decks need none)
#   COFFE_NGSPICE_TIMEOUT  seconds per point (default 600)
#   COFFE_NGSPICE_THREADS  ngspice threads per run ("set num_threads" in .spiceinit; default 1: one sweep point
#                          per core). ngspice ignores OMP_NUM_THREADS and otherwise threads over every core,
#                          which a container's CPU quota throttles: sb_mux 5.95 s at 2 CPUs, 0.85 s with one thread
#   COFFE_NGSPICE_WORKERS  sweep points run at once (default 1)
#   COFFE_NGSPICE_KEEP     1 keeps each point's deck and log beside its record (default: record only)
#   COFFE_NGSPICE_POINTS   folder of the point folders (default <deck folder>/points); put it outside
#                          COFFE's output folder, which COFFE empties when it starts, to resume a stopped run

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import coffe.ngspice_dialect as dialect
import coffe.spice as spice


def _hatf_tech():
    """ Import the hatf-tech deck interface, with a clear message when it is not on the path. """

    try:
        from conexus_hatf_tech.simulators import NgspiceBackend
        from conexus_hatf_tech.simulators.decks import DataSweep, ForeignDeck
    except ImportError as exc:
        raise ImportError(
            "COFFE_SIMULATOR=ngspice needs conexus_hatf_tech (HATF-TECH-M0.3 or later) importable: "
            "put the hatf-tech src/ checkout and its dependencies on PYTHONPATH"
        ) from exc
    return NgspiceBackend, DataSweep, ForeignDeck


## The include each point's deck reads its values from, next to the deck.
POINT_INCLUDE = "sweep_point.l"


class NgspiceInterface(spice.SpiceInterface):
    """
    Runs COFFE's HSPICE decks on ngspice, one run per sweep point.
    run() returns what SpiceInterface.run() returns, so the rest of COFFE is unchanged.
    """

    def __init__(self, executable=None, osdi_path=None, timeout=None, workers=None):

        spice.SpiceInterface.__init__(self)
        NgspiceBackend, self._DataSweep, ForeignDeck = _hatf_tech()
        executable = executable or os.environ.get("COFFE_NGSPICE") or "ngspice"
        osdi_path = os.environ.get("COFFE_NGSPICE_OSDI", "") if osdi_path is None else osdi_path
        self.backend = NgspiceBackend(executable=executable, osdi_path=osdi_path)
        # Each point's deck runs in its own folder and includes its values from there.
        self.foreign = ForeignDeck(self.backend, include_name=POINT_INCLUDE)
        self.timeout = float(timeout or os.environ.get("COFFE_NGSPICE_TIMEOUT", "600"))
        self.workers = max(1, int(workers or os.environ.get("COFFE_NGSPICE_WORKERS", "1")))
        self.keep = os.environ.get("COFFE_NGSPICE_KEEP", "") == "1"
        self.points = os.environ.get("COFFE_NGSPICE_POINTS", "")
        self.threads = int(os.environ.get("COFFE_NGSPICE_THREADS", "1"))
        # ngspice copies of the libraries, per includes file (one per architecture folder).
        self.libraries = {}

        return


    def run(self, sp_path, parameter_dict):
        """
        Run the deck at 'sp_path' once per point of 'parameter_dict' (same format as
        SpiceInterface.run) and return {meas_name: [value per point]}, values as strings
        or "failed".
        """

        sp_path = Path(os.path.abspath(sp_path))
        run_dir = sp_path.parent

        # Keep COFFE's easy-to-read data.txt for debugging; sweep_data.l is rewritten per point below.
        self._setup_data_sweep_file(parameter_dict)

        sweep = self._DataSweep.from_columns(parameter_dict)
        text, coffe_rules, libraries = self._coffe_dialect(sp_path)
        digest = hashlib.sha256((text + "".join(libraries)).encode()).hexdigest()[:16]  # the deck and every library it reads
        rules = [{"rule": rule, "count": count} for rule, count in coffe_rules]

        def one(point):
            return self._point(sp_path, text, digest, rules, point)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            records = list(pool.map(one, sweep.points()))

        measurements = {}
        meas_names = []
        for record in records:
            for name, value in record["coffe"].items():
                if name not in measurements:
                    measurements[name] = []
                    meas_names.append(name)
                measurements[name].append(value)

        with open(run_dir / "ngspice_runs.jsonl", "a") as record_file:
            for record in records:
                record_file.write(json.dumps(record) + "\n")

        self.simulation_counter += len(sweep.rows)

        return spice.combine_meaz(measurements, meas_names)


    def _coffe_dialect(self, sp_path):
        """ The deck on the ngspice copies of COFFE's libraries, port probes resolved (coffe/ngspice_dialect.py), reading its
        values from POINT_INCLUDE; also written as <stem>.coffe.sp beside the deck. Returns the text, the rules applied and
        the original libraries' texts. """

        with open(sp_path) as handle:
            text = handle.read()
        match = re.search(r"""(?im)^\s*\.lib\s+["']([^"']*includes\.l)["']""", text)
        if match is None:
            return text + '\n.INCLUDE "' + POINT_INCLUDE + '"\n', [], []
        includes = os.path.normpath(os.path.join(str(sp_path.parent), match.group(1)))
        if includes not in self.libraries:
            self.libraries[includes] = dialect.CoffeLibraries(includes)
        translated, rules = self.libraries[includes].deck_for_points(text, POINT_INCLUDE)
        (sp_path.parent / (sp_path.stem + ".coffe" + sp_path.suffix)).write_text(translated)
        return translated, rules, self.libraries[includes].texts


    def _point(self, sp_path, text, digest, rules, point):
        """ One sweep point in its own folder; its record (reused when one for the same deck is there). """

        base = Path(self.points) / sp_path.parent.name if self.points else sp_path.parent / "points"
        folder = base / (sp_path.stem + "." + point.point_id)
        saved = folder / "record.json"
        if saved.is_file():
            try:
                record = json.loads(saved.read_text())
                if record.get("deck_digest") == digest and record.get("values") == point.values:
                    record["resumed"] = True
                    return record
            except ValueError:
                pass  # a record torn by a stop: run the point again
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        deck = folder / sp_path.name
        deck.write_text(text)
        prepared = self.foreign.prepare(deck, folder, point=point)
        with open(folder / ".spiceinit", "a") as spiceinit:
            spiceinit.write("set num_threads=%s\n" % self.threads)
        start = time.time()
        log = self._simulate(prepared.deck)
        seconds = round(time.time() - start, 2)
        [measures] = self.foreign.read(prepared, log)
        record = prepared.record()
        record.update({
            "deck_digest": digest, "coffe_rules": rules, "seconds": seconds, "resumed": False,
            "status": {m.name.lower(): m.status for m in measures}, "coffe": {m.name.lower(): m.as_coffe() for m in measures},
        })
        if not self.keep:
            for path in folder.iterdir():
                if path.is_file():
                    path.unlink()
        temporary = folder / "record.json.tmp"
        temporary.write_text(json.dumps(record))
        temporary.replace(saved)  # whole or not at all
        return record


    def _simulate(self, deck):
        """ Run ngspice in batch mode in the deck's folder; the log goes next to the deck (.lis) and is returned. """

        command = self.backend.command(deck)
        try:
            env = dict(os.environ, OMP_NUM_THREADS=os.environ.get("COFFE_NGSPICE_THREADS", "1"))
            completed = subprocess.run(command, cwd=deck.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=self.timeout)
            log = completed.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            log = (exc.stdout or b"").decode("utf-8", errors="replace") + "\n*** timeout after %g s\n" % self.timeout
        except FileNotFoundError:
            print("----------------------------------------------------------")
            print("              ngspice not found: " + command[0])
            print("----------------------------------------------------------")
            exit(2)
        (deck.parent / (deck.stem + ".lis")).write_text(log)
        return log


def make_interface():
    """ The SPICE interface COFFE_SIMULATOR names: hspice (default, upstream) or ngspice. """

    simulator = os.environ.get("COFFE_SIMULATOR", "hspice").lower()
    if simulator == "ngspice":
        return NgspiceInterface()
    if simulator == "hspice":
        return spice.SpiceInterface()
    raise ValueError("COFFE_SIMULATOR must be hspice or ngspice, not " + simulator)
