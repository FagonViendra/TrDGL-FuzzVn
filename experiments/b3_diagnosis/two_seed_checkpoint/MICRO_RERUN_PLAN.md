# B3 Diagnostic Micro-Rerun Plan

## Goal

Discriminate among four explanations with the smallest controlled rerun that still covers all ten API groups:

1. 600-token ceiling is the primary problem;
2. missing explicit turn stops are the primary harness problem;
3. chat-template application differs from a forced manual Gemma prompt;
4. B3 remains defective across harness variants, shifting suspicion toward the model artifact or unavailable upstream pipeline.

No result is assumed here.

## Fixed prompt set

Use one API from every frozen group, selected deterministically from the supplied evidence to favor a successful B2 control and an observed B3 delimiter phenotype:

| Group | API |
|---|---|
| autograd_transform_compile_and_export | `torch.compile` |
| convolution_and_pooling | `torch.nn.functional.avg_pool3d` |
| fft_and_spectral | `torch.fft.irfft2` |
| indexing_gather_and_scatter | `torch.take` |
| linear_algebra | `torch.mm` |
| normalization_activation_and_loss | `torch.nn.functional.silu` |
| reduction_and_statistics | `torch.var` |
| shape_and_composition | `torch.flatten` |
| sparse | `torch.sparse_csr_tensor` |
| tensor_creation | `torch.tensor` |

Use both frozen generation seeds: 3407 and 7711. This creates 20 prompt instances. Use the exact full B2/B3 prompt bytes from the frozen runner and verify their SHA-256 values before generation.

## Experimental matrix

Run one fresh B2 control and four B3 conditions for each prompt instance:

| Cell | Model | Invocation | Turn stops | `max_tokens` | Diagnostic purpose |
|---|---|---|---|---:|---|
| C0 | B2 base | frozen primary chat path | none | 600 | Fresh environment/control check |
| C1 | B3 tuned | frozen primary chat path | none | 600 | Reproduce original phenotype/new signature |
| C2 | B3 tuned | frozen primary chat path | none | 1200 | Test whether more budget completes a valid first answer or merely extends runaway generation |
| C3 | B3 tuned | primary chat path | `<end_of_turn>`, `<start_of_turn>` | 600 | Test explicit stop containment |
| C4 | B3 tuned | forced `manual_gemma_prompt` completion | same explicit stops | 600 | Separate chat-template application from weight/artifact behavior |

Total maximum: `20 prompt instances × 5 cells = 100 generations`.

C0 may be analytically paired with each B3 condition because prompt, seed, environment, and evaluation are fixed. Do not reuse old B2 output as the only control; a fresh C0 detects runtime or package drift.

## Order control

The frozen two-seed evidence confounds seed and order. Correct that here:

- Seed 3407: groups 1–5 run C0 before C1; groups 6–10 run C1 before C0.
- Seed 7711: reverse those assignments.
- C2–C4 follow a deterministic Latin rotation by API index so each B3 condition appears equally often in each subsequent position.
- Batch model loads only where necessary, but preserve the predeclared logical/physical order in event metadata.

Record `physical_execution_index`, `generation_path`, effective `llama_chat_format`, chat-template SHA-256, EOS token id, response `usage`, actual load `(n_ctx,n_gpu_layers)`, and raw generated token ids if storage permits.

## Preflight checks

Before any generation:

1. Verify both GGUF file SHA-256 values against the manifests.
2. Dump B2 and B3 GGUF metadata with official `gguf_dump.py`.
3. Compare `tokenizer.chat_template`, EOS/BOS ids, add-EOS/add-BOS flags, special-token tables, architecture, tensor inventory, and quantization metadata.
4. Render and hash the exact prompt for C1, C3, and C4.
5. Dry-run the patched runner and confirm the new `RUNNER_VERSION` changes the run signature.
6. Write to a new output directory; never append to the frozen evidence logs.

A metadata mismatch is evidence about the artifact and should be reported before generation, but it is not by itself proof that it caused the output behavior.

## Measurements

For every cell/event preserve:

- raw output and SHA-256;
- response finish reason and `usage.completion_tokens` when available;
- post-hoc raw-token count, clearly labeled as retokenized text;
- exact generated token ids and first EOS/turn-token position when available;
- complete/partial Gemma delimiter counts;
- first-turn span and whether generation continued after it;
- parseable, runnable, target-valid, oracle-bearing;
- generation time;
- selected chat format/template hash/EOS id;
- exception and branch telemetry.

Do not replace raw output with a salvaged first turn. A separately derived `first_turn_output` field is acceptable if raw output remains immutable.

## Decision matrix

| Observation | Interpretation |
|---|---|
| C2 reaches 1200 and continues role cycling; C3 stops near first delimiter | Token ceiling is a symptom; missing/ineffective stopping is directly implicated. |
| C2 produces a complete valid first answer before 1200 without role cycling | 600 ceiling contributes materially, though original delimiter leakage still requires explanation if present. |
| C3 improves strongly; C4 is similar | Explicit stop containment is sufficient for the harness, but EOS/template metadata may still be wrong. |
| C3 fails but C4 improves | Primary chat-template application/metadata selection is implicated. |
| C3 and C4 both stop cleanly but first-turn code is still repetitive/invalid | Turn stopping fixes runaway continuation, not B3 content quality; artifact-level model behavior remains. |
| All B3 cells fail while C0 succeeds | Harness variants tested do not rescue B3; inspect source/pre-quantized model, merge, conversion, tokenizer, and training artifacts. Do not call it training collapse yet. |
| C0 also collapses or metadata differs from the frozen manifest | Environment/model-file drift invalidates causal comparison; stop and repair the setup. |

## Hard budget and stopping rule

Hard wall-clock budget: **60 minutes**, including model loading and preflight, on the same class of T4 environment used by the manifests.

Expected generation-only time from the frozen checkpoint is roughly 31 minutes for 100 generations at about 18.6 seconds each; the remaining budget covers model swaps and validation.

Stop immediately if:

- any file hash differs from the declared artifact;
- prompt hashes differ across paired cells;
- the run signature collides with an old signature;
- event logging omits branch/template/EOS telemetry;
- five consecutive generations crash or time out in the same cell;
- wall clock reaches 60 minutes.

Adaptive economy rule: after C2 has completed all ten groups for seed 3407, it may be terminated early only if all ten outputs both (a) reach the 1200-token ceiling and (b) continue delimiter/role cycling after the first answer. Mark seed-7711 C2 as unrun rather than imputing it. C0, C1, C3, and C4 must still cover both seeds and all ten groups.

## Minimum report

Report cell-by-cell counts and paired deltas. State explicitly which cells were actually run, which stopping rule fired, and which hypotheses remain unverified. Do not fold this micro-rerun into the frozen two-seed result or present it as the planned five-seed campaign.
