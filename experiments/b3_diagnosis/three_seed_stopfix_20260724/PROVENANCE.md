# B3 continuation provenance

The 24 July continuation covers B3 Q3_K_M for seeds `12011`, `19001`, and
`27103`.

## Reused benchmark inputs

- All 360 rows retain benchmark ID `trdgl_pytorch_120_v1`.
- The task IDs, 120-API documentation snapshot, generation seeds, and scheduled
  baseline order come from the frozen five-seed benchmark.
- For every API, the frozen continuation prompt hash matches the prompt hash of
  the original B2 and B3 full-prompt rows. The comparison found 0 mismatches
  across 120 APIs.
- B3 does not read or transform generated B1/B2 programs. B1 uses the minimal
  prompt; B2 and B3 use the same full prompt with different model policies.

## Model and environment

- The continuation uses the same tuned B3 Q3_K_M artifact as the original
  checkpoint: SHA-256
  `2f35a80c395f31c1b39003d1e4e14df6b06796f343bb670c37d53828a96e482b`.
- The Q3 decoding contract remains `n_ctx=2048`, `max_tokens=600`,
  `temperature=0.2`, `top_p=0.95`, `top_k=40`, `min_p=0.05`, and
  `repeat_penalty=1.08`.
- The original balanced checkpoint records a Tesla T4. The Snowflake
  continuation environment records an NVIDIA RTX PRO 6000 Blackwell and
  `llama-cpp-python 0.3.23` with CUDA `sm_120`; this faster environment was used
  to avoid the T4 throughput bottleneck.

## Interpretation boundary

The continuation is not a hardware-only rerun. Its serving wrapper adds
string-level turn-marker stops and removes complete or orphaned marker
fragments. Generated programs are evaluated separately in CPU subprocesses.
Therefore the 360 B3 rows establish continuation and serving-repair evidence,
but they cannot be pooled with the original B2/B3 comparison until compatible
B0, B1, and B2 rows are available.
