# COFFE2 runs against flut_report.txt

## Timing

| run | simulator | max step | workers | host | CPU | wall (h) | CPU (h) | simulations | s per simulation | sb_mux s per point |
|---|---|---|---|---|---|---|---|---|---|---|
| ngspice-5p | ngspice | 5p | 2 | sssThinkpadE14 | 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz | 0.06 | 0.11 | 30 | 6.364 | 2.6 |

## Accuracy

### ngspice-5p ngspice 5p tier A

| | archive (HSPICE) | this run | difference |
|---|---|---|---|
| tile area (um2) | 1255.13 | 1114.07 | -11.2 % |
| critical path (ps) | 151.62 | 205.31 | +35.4 % |
| simulations | 162426 | 30 | |

| subcircuit | delay archive (ps) | delay run | delay diff % | area archive (um2) | area run | area diff % |
|---|---|---|---|---|---|---|
| sb_mux | 184.5 | 174.109 | -5.6 | 1.769 | 1.254 | -29.1 |
| sb_mux(with sram) | 184.5 | 174.109 | -5.6 | 2.717 | 2.202 | -19.0 |
| cb_mux | 124.7 | 139.701 | +12.0 | 3.493 | 3.386 | -3.1 |
| cb_mux(with sram) | 124.7 | 139.701 | +12.0 | 5.661 | 5.554 | -1.9 |
| local_mux | 70.15 | 48.9394 | -30.2 | 1.363 | 1.615 | +18.5 |
| local_mux(with sram) | 70.15 | 48.9394 | -30.2 | 2.853 | 3.105 | +8.8 |
| local_ble_output(with sram) | 123.9 | 126.514 | +2.1 | 0.66 | 0.453 | -31.4 |
| general_ble_output(with sram) | 37.68 | 45.9266 | +21.9 | 0.633 | 0.469 | -25.9 |
| ff | - | - | - | 1.228 | 1.228 | +0.0 |
| lut(with sram) | 143.0 | 328.242 | +129.5 | 29.144 | 26.19 | -10.1 |
| lut_a | 207.34 | 438.971 | +111.7 | - | - | - |
| lut_a_driver | 14.57 | 38.8505 | +166.6 | 0.311 | 0.093 | -70.1 |
| lut_a_driver_not | 20.09 | 41.8816 | +108.5 | 0.415 | 0.166 | -60.0 |
| lut_b | 207.14 | 438.235 | +111.6 | - | - | - |
| lut_b_driver | 13.04 | 32.0811 | +146.0 | 0.286 | 0.093 | -67.5 |
| lut_b_driver_not | 19.31 | 33.6987 | +74.5 | 0.38 | 0.166 | -56.3 |
| lut_c | 186.94 | 424.849 | +127.3 | - | - | - |
| lut_c_driver | 30.24 | 70.6756 | +133.7 | 0.902 | 0.377 | -58.2 |
| lut_c_driver_not | 35.11 | 73.6093 | +109.7 | 0.342 | 0.166 | -51.5 |
| lut_d | 128.38 | 260.455 | +102.9 | - | - | - |
| lut_d_driver | 14.35 | 28.0364 | +95.4 | 0.194 | 0.093 | -52.1 |
| lut_d_driver_not | 20.55 | 30.9671 | +50.7 | 0.28 | 0.166 | -40.7 |
| lut_e | 126.71 | 258.404 | +103.9 | - | - | - |
| lut_e_driver | 15.96 | 26.6856 | +67.2 | 0.145 | 0.093 | -35.9 |
| lut_e_driver_not | 22.61 | 30.1961 | +33.6 | 0.223 | 0.166 | -25.6 |
| lut_f | 64.94 | 125.232 | +92.8 | - | - | - |
| lut_f_driver | 13.66 | 25.8374 | +89.1 | 0.17 | 0.093 | -45.3 |
| lut_f_driver_not | 19.46 | 29.6976 | +52.6 | 0.263 | 0.166 | -36.9 |
| carry_chain | 22.88 | 51.9242 | +126.9 | 1.159 | 0.872 | -24.8 |
| carry_chain_perf | 29.68 | 47.6224 | +60.5 | 0.095 | 0.073 | -23.2 |
| carry_chain_mux | 79.02 | 99.3761 | +25.8 | 0.775 | 0.469 | -39.5 |
| carry_chain_inter | 18.64 | 44.6743 | +139.7 | 0.369 | 0.166 | -55.0 |
| xcarry_chain_and | 51.61 | 66.6111 | +29.1 | 0.313 | 0.291 | -7.0 |
| xcarry_chain_mux | 58.11 | 62.0773 | +6.8 | 0.399 | 0.469 | +17.5 |

Mean |delay difference| over 33 subcircuits: 73.2 %; largest 166.6 %.

