# TrDGL-FuzzVn experiment protocol

This protocol separates archived measurements from experiments that still require a controlled rerun. It is the execution checklist for completing every experimental item requested by the supervisor without mixing incompatible runs or inventing unavailable counters.

## Evidence status

| Requested evidence | Current evidence | Status |
|---|---|---|
| Expanded PyTorch API benchmark | Same-harness 40-API base-vs-tuned run, extending the original 24-API set | Reported in Section 4.3 |
| Random/template baseline | No compatible archived run | Controlled rerun required |
| Base, prompt-only, tuned LLMs | Base and tuned: 40 APIs; base and tuned: 18 oracle prompts; prompt-only is defined but not isolated | Prompt-only rerun required |
| Larger prompt set and multiple seeds | One archived output per API/prompt | Multi-seed rerun required |
| AST/oracle/Vn/Atlas/fine-tuning ablation | Oracle and fine-tuning contrasts exist; AST, Vn, and Atlas were not independently disabled | Replay required |
| Vn raw-to-promoted funnel | Only partial campaign-specific counters exist | Unified JSONL replay required |
| Candidate verification ledger | Five candidate/family rows with explicit missing states | Reported in Section 4.7 |
| Generation-error taxonomy | Target miss, runtime failure, missing oracle, and fake-assertion criteria defined | Full raw-output labeling required |
| Numerical oracle matrix | Fault injection, clean controls, CPU/GPU and eager/compiled examples exist | Full factorial rerun required |
| Atlas evaluation | Corpus size and cluster count exist | Retrieval intervention rerun required |
| Reproducibility and throughput | Archived environment/runtime data reported | Container and command manifest still required |

## Frozen benchmark

The completion benchmark is frozen as `trdgl_pytorch_120_v1`: exactly 120 curated public PyTorch APIs, with 12 APIs in each of ten groups (tensor creation; shape/composition; reductions/statistics; linear algebra; convolution/pooling; normalization/activation/loss; indexing/gather/scatter; sparse; FFT/spectral; and autograd/transform/compile/export). The canonical manifest SHA-256 is `d9de15ca10bdd4abef2106c58b661197f69d1f278f87eec2b6eb56845f4facac`. The manifest, integrity check, runtime validator, paired task builder, true decoding-seed plumbing, B0/B1/B2/B3 runner, subprocess evaluator, and resumable JSONL checkpoint are embedded in the single self-contained notebook `experiments/benchmark_120/trdgl_fair_benchmark_120.ipynb`; runtime introspection may validate the list but may not replace its members.

Use the five frozen generation seeds `3407`, `7711`, `12011`, `19001`, and `27103` per API and the same prompt budget, decoding parameters, timeout, imports, dependency environment, subprocess wrapper, and GPU allocation for every generator. The seed must be passed to the model sampler as well as host/framework RNGs; it is not merely an API-selection seed. A Latin rotation over API and seed indices places every baseline exactly 150 times in each run-order position:

- B0: typed random/template fuzzer;
- B1: base LLM with the minimal task prompt;
- B2: base LLM with the full TrDGL prompt but no adapter;
- B3: the fine-tuned model with the same full prompt.

The unit of analysis is an API/seed pair. Report bootstrap 95% confidence intervals and paired comparisons because every baseline sees the same API/seed matrix.

## Required event record

Each generation emits one append-only JSONL record containing:

```text
run_id, baseline, model_revision, api, api_group, generation_seed,
prompt_hash, raw_output_hash, parses, target_call_present, imports_resolve,
shape_valid, dtype_valid, subprocess_exit, timeout, oracle_present,
oracle_kind, fake_assertion, reproduced, minimized, duplicate_cluster,
stable_status, nightly_status, promoted, rejection_reason, wall_seconds
```

The raw-to-promoted funnel is computed only from this record stream:

1. raw generations;
2. Python parse success;
3. target-call and AST-policy success;
4. subprocess execution success;
5. genuine oracle present;
6. anomaly triggered;
7. reproduced;
8. minimized;
9. duplicate check passed;
10. stable/nightly classification completed;
11. promoted candidate.

## Generation-error labels

Labels are deterministic and may co-occur:

- wrong or missing target API;
- missing or invalid import;
- syntax/AST-policy failure;
- invalid shape/rank;
- unsupported dtype/device/layout;
- timeout, OOM, interpreter crash, or ordinary exception;
- missing oracle;
- fake assertion (constant, tautological, compares a value with itself, or catches and suppresses every failure);
- nondeterministic failure;
- duplicate candidate.

Two reviewers independently label a stratified sample; disagreements are adjudicated and inter-rater agreement is reported.

## Ablation replay

Freeze the raw B3 generations, then replay the same corpus under:

- no AST policy;
- no numerical/differential oracle;
- no Vn gate;
- no Atlas retrieval;
- the full pipeline.

Fine-tuning is the only ablation that regenerates programs: compare B2 and B3 with paired API/seed inputs. Report runnable rate, valid-program rate, genuine-oracle rate, anomalies, reproduced candidates, duplicate rejection, promotion rate, and reviewer minutes per promoted candidate.

## Numerical-oracle matrix

For every suitable program, run CPU and CUDA, eager and compiled execution, forward comparison and gradient comparison, with float32/float64 references where supported. Record absolute and relative error, ULP distance, dtype, tensor magnitude, backend, compiler, and tolerance source. Compare the certified program-specific bound with fixed thresholds of `1e-3`, `1e-4`, and `1e-5` on clean controls and injected numerical defects.

## Atlas intervention

Run the same candidate summaries with Atlas retrieval enabled and disabled. Measure:

- candidates matched to an existing cluster;
- duplicates rejected before manual triage;
- prompts whose API/error-family selection was guided by Atlas;
- unique reproduced candidates per 1,000 generations;
- manual triage time.

Do not count a retrieved issue as a confirmed duplicate until the reproducer, affected versions, and failure signature agree.

## Candidate release rule

A candidate may be called “promoted” only when its minimized reproducer passes repeated execution, duplicate search is recorded, and both stable and nightly/main status are known. Any absent field remains “pending”; it is never interpreted as false or zero.

## Reproducibility bundle

The final artifact must include the frozen API list, prompts, model and adapter hashes, environment lockfile/container digest, CUDA/driver/GPU details, five generation seeds, raw generations, JSONL gate log, minimized reproducers, Atlas snapshot/hash, aggregation script, exact commands, total GPU/CPU hours, wall time, and throughput in generations and executed tests per hour.
