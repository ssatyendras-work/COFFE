# Co-Nexus: COFFE2 on ngspice (branch `conexus-ngspice`)

COFFE2 as released runs HSPICE. This branch adds ngspice beside it, chosen per run with
`COFFE_SIMULATOR=ngspice` (default `hspice`: unchanged). `master` stays at the RDS-TOOL pin (0987102)
for the HSPICE reference runs.

| File | What |
|---|---|
| `coffe/ngspice_interface.py` | `NgspiceInterface`: `run(sp_path, parameter_dict)` as `SpiceInterface`, one ngspice run per sweep point; `make_interface()` reads `COFFE_SIMULATOR` |
| `coffe/ngspice_dialect.py` | what COFFE's decks need beyond hatf-tech's generic rules: `bare_rc_param`, `source_param` (braces), `port_probe` (hierarchical port names resolved to nets) |
| `coffe/spice.py` | `combine_meaz` factored out of `parse_mt0`, shared by both simulators; `import sys` it lacked |
| `tests/test_conexus_ngspice.py` | 7 tests, a fake ngspice; `python -m pytest tests/test_conexus_ngspice.py` |

Deck preparation and measure parsing are hatf-tech's foreign-deck interface (HATF-TECH-M0.3,
`conexus_hatf_tech.simulators.decks`, from c45f21c; a38fa06 for decks without OSDI): `DataSweep` points
with stable ids, `ForeignDeck` (drop `SWEEP DATA`, `INTEGRAL` to `INTEG`, `set ngbehavior=hsa`), typed
`Measure`s. Every point's record (point id, values, rules and counts, measure status) is appended to
`ngspice_runs.jsonl` beside the deck. The libraries are copied to `<name>.ngspice.l`; the originals
are untouched, so HSPICE can run the same folder.

Environment: `COFFE_NGSPICE` (executable), `COFFE_NGSPICE_OSDI` (empty for bulk and PTM decks),
`COFFE_NGSPICE_TIMEOUT` (s per point, 600), `COFFE_NGSPICE_THREADS` (OpenMP threads, 1).
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

Not yet: sizing runs (thousands of points; one ngspice process per point, sequential), FinFET
decks (ASAP7 cards through OSDI BSIM-CMG), a comparison with HSPICE on the same tiles (G0.4b, on Slurm).
