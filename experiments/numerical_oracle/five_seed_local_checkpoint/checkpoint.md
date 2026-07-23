# Five-seed local numerical-oracle diagnostic

This is a complete local-validation design, not a complete measured paper factorial.

## Coverage and outcomes

- 480 designed events across five seeds, CPU/CUDA, eager/compiled, forward/gradient, float32/float64, clean/injected, and three fixed tolerances.
- Eager measured: 240/240; compiled measured: 0/240 (all compiled cells are explicitly unsupported on this Windows host).
- Clean eager controls: 0/120 false positives.
- Injected delta 2e-4 detection: 40/40 at 1e-5, 40/40 at 1e-4, and 0/40 at 1e-3.
- Protocol wall time: 4.256954 s (112.757 designed events/s; interpreter import excluded).

## Environment

- Python 3.11.9; PyTorch 2.6.0+cu124; CUDA runtime 12.4; driver 592.27.
- GPU: NVIDIA GeForce RTX 3050 Ti Laptop GPU.

## Clean-control numerical maxima

| Device | Check | Dtype | Max abs | Max rel | Max ULP |
|---|---|---:|---:|---:|---:|
| cpu | forward | float32 | 9.48233e-08 | 6.20429e-07 | 6 |
| cpu | forward | float64 | 0 | 0 | 0 |
| cpu | gradient | float32 | 1.16395e-07 | 4.26553e-06 | 57 |
| cpu | gradient | float64 | 0 | 0 | 0 |
| cuda | forward | float32 | 1.23232e-07 | 3.9498e-07 | 4 |
| cuda | forward | float64 | 2.22045e-16 | 3.81796e-16 | 2 |
| cuda | gradient | float32 | 1.07616e-07 | 4.26553e-06 | 69 |
| cuda | gradient | float64 | 2.22045e-16 | 3.56143e-15 | 32 |

## Claim boundary

Complete five-seed local diagnostic design only. CPU/CUDA eager cells are measured; compiled cells are unsupported and certified-bound evidence is absent, so this is not the matched paper result.
