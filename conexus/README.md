# Co-Nexus: COFFE2 on ngspice (branch `conexus-ngspice`)

COFFE2 as released runs HSPICE. This branch adds ngspice and Spectre beside it, chosen per run with
`COFFE_SIMULATOR=ngspice|spectre` (default `hspice`: unchanged). Spectre (hatf-tech `SpectreBackend`, ADR-0008
amendment 1) uses the same per-point path on COFFE's own libraries, with `COFFE_SPECTRE` and `COFFE_SPECTRE_FLAGS`. `master` stays at the RDS-TOOL pin (0987102)
for the HSPICE reference runs.

| File | What |
|---|---|
| `coffe/ngspice_interface.py` | `NgspiceInterface`: `run(sp_path, parameter_dict)` as `SpiceInterface`, one ngspice run per sweep point; `make_interface()` reads `COFFE_SIMULATOR` |
| `coffe/ngspice_dialect.py` | what COFFE's decks need beyond hatf-tech's generic rules: `bare_rc_param`, `source_param` (braces), `port_probe` (hierarchical port names resolved to nets), `tran_tmax` (maximum time step) |
| `conexus/subcircuit_probe.py` | one subcircuit at COFFE's initial sizes, then an N-point sizing-like sweep, timed per point |
| `coffe/spice.py` | `combine_meaz` factored out of `parse_mt0`, shared by both simulators; `import sys` it lacked |
| `tests/test_conexus_ngspice.py` | 7 tests, a fake ngspice; `python -m pytest tests/test_conexus_ngspice.py` |

Deck preparation and measure parsing are hatf-tech's foreign-deck interface (HATF-TECH-M0.3,
`conexus_hatf_tech.simulators.decks`, from c45f21c; a38fa06 for decks without OSDI): `DataSweep` points
with stable ids, `ForeignDeck` (drop `SWEEP DATA`, `INTEGRAL` to `INTEG`, `set ngbehavior=hsa`), typed
`Measure`s. Every point's record (point id, values, rules and counts, measure status) is appended to
`ngspice_runs.jsonl` beside the deck. The libraries are copied to `<name>.ngspice.l`; the originals
are untouched, so HSPICE can run the same folder.

Environment: `COFFE_NGSPICE` (executable), `COFFE_NGSPICE_OSDI` (empty for bulk and PTM decks),
`COFFE_NGSPICE_TIMEOUT` (s per point, 600), `COFFE_NGSPICE_THREADS` (OpenMP threads, 1),
`COFFE_NGSPICE_TMAX` (maximum time step appended to `.TRAN`, `5p`; empty for none).
`conexus_hatf_tech` must be importable; in the technology image 0.2.0 (whose COFFE venv also lacks
PyYAML, which COFFE2 imports):

```bash
docker run --rm --cpus 2 -v <this checkout>:/coffe:ro -v <hatf-tech>/src:/hatf-src:ro -v <work>:/work -w /work \
  -e COFFE_SIMULATOR=ngspice -e COFFE_NGSPICE_OSDI= -e HOME=/work \
  -e PYTHONPATH=/coffe:/hatf-src:/opt/conexus/py/lib/python3.12/site-packages \
  --entrypoint /opt/conexus/coffe-venv/bin/python registry.conexus.local/hatf-tech/technology:0.2.0 \
  /coffe/coffe.py -n /work/<input>.yaml
```

## Evidence (ThinkPad, 2026-11-05, 2 CPUs, nice 10)

`input_files/bulk_example.txt` as YAML (`evidence/bulk_22nm_no_sizing.yaml`: K6 N10 W320 L4 I40, PTM
22 nm bulk HP), `-n` (no sizing): 24 ngspice runs over 12 subcircuits, every measure `ok`; tile
887.2 um2, representative critical path 175.96 ps, 12 min 19 s (`evidence/*.report.txt`,
`*.ngspice_runs.jsonl`). sb_mux 2-point sweep: point 0 equals the single run (157.0 / 102.1 ps
fall / rise); with the second inverter twice as wide 130.1 / 91.0 ps and 14.1 uW instead of 13.5.

Transmission gates (`evidence/tg_sb_mux_*`, `bulk_22nm_tg.yaml`, run before `tran_tmax`): sb_mux with
`switch_type: transmission_gate` at COFFE's initial sizes and an 8-point sweep of its 8 transistors (1x to 2x):
9 runs, every measure ok; 206.1 / 159.2 ps fall / rise falling to 155.3 / 124.9 ps; 62.6 s per point.

Threads: ngspice ignores OMP_NUM_THREADS and threads over every core; under a container's CPU quota that is
throttled (sb_mux at 2 CPUs: 5.95 s default, 0.85 s with `set num_threads=1`). Each point's `.spiceinit` now pins
`COFFE_NGSPICE_THREADS` (1) and points run in parallel instead. Single-threaded, one CPU, sb_mux per point:
1 ps 3.8 s, 5 ps 0.83 s, 20 ps 0.27 s (the archived HSPICE run averaged 0.175 s per simulation). The time-step
figures below were measured before this, with the throttled default; their accuracy holds.

Time step: ngspice caps its step at `.TRAN`'s print step (1 ps), HSPICE does not. The pass-transistor
sb_mux deck, one CPU: 54.3 s as written; maximum step 5 ps 11.3 s (total delays within 0.06 %), 20 ps
3.4 s (within 0.9 %), 100 ps 1.6 s (19 % off: too coarse). `tran_tmax` appends 5 ps by default.

3-input LUT (`coffe/lut3.py`, X-PACE G0.4c): COFFE2 builds a fracturable K-LUT from two (K-1)-input halves and had
6-, 5- and 4-LUT generators only; the 3-LUT is its 4-LUT one level shorter (node names kept, so the 4-LUT's top-level
deck measures it), with area, wire and initial-size cases in `fpga.py`, and the halves' select input named after K
(`d` for K4). Also in `fpga.py`: a routing wire's CB load was rounded per tile, which gives 0 and an impossible
negative off count when I/2 * cb_mux_size < W (I <= 12 at Fc_in 0.15, W 300: k4-N4 tiles); then the inputs are
counted over the wire (L tiles) instead, logged; other tiles keep COFFE's count. `evidence/lut3_thinkpad`: k4-N4-F1-C1
without sizing on ngspice, 24 simulations, 470.4 um2, 144.21 ps. COFFE's xcarry_chain_mux deck measures
`V(n_general_out)`, a node it does not have, so `meas_logic_low_voltage` fails there on any simulator (unused).

FinFET decks (HATF-TECH-M2.3, gate 2): ASAP7's level 72 card is rewritten for the OSDI BSIM-CMG by hatf-tech's
`coffe_tile.osdi_card` (inside its `.LIB` section, a run artifact) and, with `COFFE_NGSPICE_OSDI` set, MOSFET instances
take the N prefix (`osdi_instance` rule). A point ngspice aborts with "Timestep too small" runs again at `COFFE_NGSPICE_RETRY_TMAX` (1 ps;
pass-transistor LUT outputs at a 5 ps step), and if that fails too, also with gmin `COFFE_NGSPICE_RETRY_GMIN`
(1e-15; the initial timepoint of a pass-transistor connection-block mux driving a LUT input); the steps are recorded as
`retry` on the point, and a point whose retry failed is not reused on resume. On local_ble_output 1 ps and gear
integration agree within 0.1 %; on sb_mux gmin 1e-15 leaves delays and power unchanged to six digits. Inputs: `conexus/inputs/asap7_k6n10_pt.yaml` (COFFE's
archived 7 nm pass-transistor run, gate 2) and `asap7_k6n10_tg.yaml` (transmission gates, P1's ASAP7 switch type). The
ASAP7 cards are BSIM-CMG 107; the OSDI build is 111.2.1 and ignores coremod, capmod, nseg and etaqm (open question).

Not yet: a comparison with HSPICE on the same tiles (G0.4b, on Slurm).


## Memory caps on Hyperion (2026-11-10)

Every kit container runs with `--memory $MEMORY --memory-swap $MEMORY` (kit.env, default 32g). Hyperion's kernel has no swap accounting, so Docker ignores the swap cap ("Memory limited without swap"); host swap is 63 GB. ngspice needs a few GB per tile, so the memory cap and the tile slots (SLOTS, 3) are the protection.
