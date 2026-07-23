# B3 Root-Cause Review — Frozen Two-Seed Checkpoint

## Executive conclusion

The uploaded evidence directly establishes an **artifact/harness-level generation collapse for B3 in seeds 3407 and 7711**. It does **not** establish that the unavailable tuned weights, tokenizer metadata, GGUF conversion, merge, quantization, or training run are defective.

The immediate termination mechanism is max-token exhaustion: all 240 B3 events report `finish_reason="length"`, the declared cap is 600, and the runner's post-hoc retokenized output counts are all 599–603. The raw text shows why the cap is reached: B3 commonly emits Gemma turn delimiters, echoes instructions, and continues into synthetic user/model turns instead of ending after one program. Exact or truncated turn-delimiter text appears in 232/240 B3 outputs, versus 0/240 B2 outputs. This is a directly observed repetitive/multi-turn collapse phenotype.

A **chat-template/stop/EOS mismatch is the leading unverified mechanism**. It is not proven because the GGUF is absent and the run did not record the selected chat handler, `tokenizer.chat_template`, EOS token id, generated token ids, or whether each event used `create_chat_completion` or the manual fallback. The frozen code's primary chat path had no explicit `<end_of_turn>`/`<start_of_turn>` stops; its fallback did. The 226 B3 outputs containing complete delimiter strings are therefore strongly inconsistent with the fallback stops operating normally and strongly suggest the primary path, but branch identity is not recorded and cannot be proven for every event.

Increasing `max_tokens` alone is not a root-cause fix. B2 also reached the 600-token cap in 219/240 cases but remained parseable in 140, runnable in 134, target-valid in 95, and oracle-bearing in 88. B3 was parseable in 5, runnable in 4, target-valid in 1, and oracle-bearing in 0.

## 1. Validation and immutable evidence

Command run from the package root:

```bash
python VALIDATE_PACKAGE.py
```

PASS block:

```json
{"b3_events": 240, "b3_finish_reason_length": 240, "b3_oracle_bearing": 0, "b3_parseable": 5, "b3_runnable": 4, "b3_target_valid": 1, "complete_pairs": 240, "paired_events": 480, "prompt_mismatches": 0, "status": "PASS"}
```

No validation failure occurred. The analyzer independently rechecked every SHA-256 listed in `INVENTORY.json`; all matched. The uploaded ZIP itself had SHA-256:

```text
791a2a1719654d1ec54f11e0341b529558a31822f790943490a2ed794cc31792
```

Packaged immutable-file hashes:

| File | SHA-256 |
|---|---|
| `evidence/b2_b3_paired.jsonl` | `eb04a3a7b7097b1e2df2705a5a361d1dd384dbec72bf278fce5177769dc12bdf` |
| `evidence/b3_events.jsonl` | `6249a81563d6fa1cf1f6a9a0917ddad9c8c3a9dbc1f62124a3092ef7215418ca` |
| `evidence/documentation_snapshot.json` | `73c6ba26b7c38afa4e1b94bf2ea7a2d5480b95398e09293cd922ea961070286b` |
| `evidence/generation_errors/analysis_manifest.sanitized.json` | `e4e9c80474f159a72d381407458421a7d18c153da77dedd60b2ea5f89d4b120c` |
| `evidence/generation_errors/failure_summary.sanitized.json` | `35ffc3d686b162ee8fe620b3025635b22b5551de3b835db2bcfa032c9b907588` |
| `evidence/pair_index.csv` | `83aca38040daaee97b6c03041a1635bd72b9858a8eafa795f95ab694520bd0a9` |
| `evidence/run_manifest_seed3407.json` | `0e54a8546c34ad6087d7e7567c426333eb8d38b4968e45da356f8bbf779399c3` |
| `evidence/run_manifest_seed7711.json` | `7a2b2089912f6ad40f160002bbc6391e9b68b3a09b17cf4e89d5ac93b6af780d` |
| `evidence/two_seed_summary.json` | `c57dc82134dbab6d10e8dcf7e17d96a702161d9ceea49cc48358fcd5f72cfde8` |
| `runner/frozen_notebook.ipynb` | `f223245216f4861b329b7497720032ec7dd61548a0ef4cd8818ece8ba9f58a1d` |
| `runner/frozen_notebook_code.py` | `bb4e6810958c36f08d45073cfd09d363842a585a02f6494e72868c0089f2e282` |
| `README.md` | `63400bf0bbd301c72073d030585c0c562975291de4fd10b6eb523f19fefa3b8a` |
| `PROMPT.md` | `c8f4a30255faa8f8cf7c7414a4f055e2c7760217acb614b2baaaf9102227792d` |
| `VALIDATE_PACKAGE.py` | `cb66cfa75cfd5d7df39d8ee3e665c838a123b5871c5c7ba28cce3eddf2b49a0b` |

The new analyzer and deliverables do not rewrite any file under `evidence/` or the frozen runner.

## 2. Recomputed observed facts

### 2.1 Pair integrity and outcome counts

There are 480 paired-event records: 240 B2 and 240 B3. They form 240 complete B2/B3 pairs with zero prompt-hash mismatches. B3 has 120 events from seed 3407 and 120 from seed 7711. The dedicated `b3_events.jsonl` view exactly matches the B3 rows in `b2_b3_paired.jsonl` by `(task_id, raw_output_sha256)`.

| Metric | B2 | B3 | B3 − B2 |
|---|---:|---:|---:|
| Events | 240 | 240 | 0 |
| `finish_reason=length` | 219 | 240 | +21 |
| `finish_reason=stop` | 21 | 0 | −21 |
| Parseable | 140 | 5 | −135 |
| Runnable | 134 | 4 | −130 |
| Target-valid | 95 | 1 | −94 |
| Oracle-bearing | 88 | 0 | −88 |

Paired discordance is overwhelmingly against B3:

| Metric | Both pass | B2 only | B3 only | Both fail | Exact McNemar p |
|---|---:|---:|---:|---:|---:|
| Parseable | 4 | 136 | 1 | 99 | `1.584e-39` |
| Runnable | 3 | 131 | 1 | 105 | `4.886e-38` |
| Target-valid | 0 | 95 | 1 | 144 | `2.449e-27` |
| Oracle-bearing | 0 | 88 | 0 | 152 | `6.462e-27` |

These are descriptive tests for this frozen checkpoint, not a five-seed final inference.

### 2.2 Token ceiling: directly observed, but not sufficient as root cause

Manifest pointers:

- `evidence/run_manifest_seed3407.json#/decoding/max_tokens` = 600
- `evidence/run_manifest_seed7711.json#/decoding/max_tokens` = 600

B3 facts:

- 240/240 report `finish_reason="length"`.
- Post-hoc `raw_token_count` distribution: 599: 27; 600: 201; 601: 8; 602: 3; 603: 1.
- Every count is within three tokens of 600.

The count is **not** the response's completion-token usage. The frozen runner recomputes it with `len(llm.tokenize(raw.encode(...), add_bos=False))`; it discards `response["usage"]`. In llama-cpp-python 0.3.23, `tokenize` defaults `special=False`, so decoded control-token text can retokenize differently and produce 601–603. Therefore, `finish_reason` plus the near-cap distribution supports cap exhaustion; the post-hoc count alone should not be treated as exact generated-token telemetry.

B2 is the decisive control against the simplistic explanation “600 tokens causes failure”: 219 B2 events also report `length`, yet 134 run successfully and 88 are oracle-bearing. The cap is the terminal mechanism for B3, while the runaway content is the differentiating behavior.

### 2.3 Raw endings and structural failure

Detector definitions used by `b3_diagnostic.py`:

- Markdown fence: odd number of triple-backtick or triple-tilde fences.
- Quote: AST syntax reason reports unterminated string/triple string or incomplete f-string.
- Bracket: unmatched opening `(`, `[`, or `{` from Python tokenization, ignoring comments and strings.
- Block: final significant line is a compound-statement header ending in `:`.
- Incomplete statement: `codeop.compile_command(..., symbol="exec")` returns `None`.
- Immediate repeated suffix: the final lexical block of at least four tokens repeats contiguously at least twice.

B3 results:

| Ending/structure feature | Count |
|---|---:|
| Complete exact `<start_of_turn>` or `<end_of_turn>` text | 226 |
| Exact delimiter or truncated prefix such as `<end_of` | 232 |
| Total `<end_of_turn>` occurrences | 679 |
| Total `<start_of_turn>` occurrences | 626 |
| Unclosed Markdown fence | 1 |
| Unterminated quote/f-string | 16 |
| Unclosed bracket stack | 64 |
| Compound block header at EOF | 7 |
| `codeop` complete | 5 |
| `codeop` incomplete | 4 |
| `codeop` invalid | 231 |
| Immediate repeated suffix | 2 |

The small `codeop=incomplete` count does not contradict truncation. Most B3 outputs become invalid earlier because raw chat delimiters and echoed user/system turns are embedded after Python. `extract_python` only strips leading prose or selects the first complete fence; it does not remove later chat turns. Thus many outputs are both length-limited at the end and already syntactically invalid before EOF.

Representative event pointers:

- `evidence/b3_events.jsonl:1#/raw_output` (`torch.amax`, seed 3407): emits a program, then `<end_of_turn>`, a new user request, another model program, and starts a third program before the cap.
- `evidence/b3_events.jsonl:29#/raw_output` (`torch.empty`, seed 3407): echoes requirement prose and ends mid-sentence.
- `evidence/b3_events.jsonl:152#/raw_output` (`torch.nn.functional.max_pool1d`, seed 7711): marker-free tail ends at `torch.max(window,` with an unclosed parenthesis.
- `evidence/b3_events.jsonl:224` (`torch.take_along_dim`, seed 7711): the sole target-valid B3 event is runnable but has no accepted oracle; it still contains turn-delimiter text.

### 2.4 Repetition and cross-task template collapse

The collapse is structural rather than byte-identical:

- Unique raw output hashes: B2 240/240; B3 240/240.
- Median 4-gram repeat fraction: B2 0.158; B3 0.364.
- Median 8-gram repeat fraction: B2 0.030; B3 0.257.
- Cross-API 5-gram Jaccard p99: B2 0.054; B3 0.147.
- Exact role-sequence motifs repeat across tasks: `user>model` occurs 70 times, `user>model>user>model` 52 times, and a single generated `user` turn 36 times.
- The phrase “Generate a unit test” appears in 91 B3 outputs; `Requirements:` appears in 63; `Documentation snapshot:` in 32. None of these phrases occurs in B2 raw outputs.

Same-API cross-seed 5-gram similarity is actually lower for B3 (median 0.132) than B2 (0.207). That argues against one fixed byte-level canned answer. B3 instead falls into related prompt-echo/multi-turn motifs with substantial stochastic variation.

### 2.5 Failure classes

Harness error labels:

| Failure class | B2 | B3 |
|---|---:|---:|
| Syntax | 100 | 235 |
| Wrong API | 39 | 3 |
| Runtime | 6 | 1 |
| No oracle | 4 | 1 |
| Fake assertion | 3 | 0 |
| None | 88 | 0 |

The event-level diagnostic clustering in `b3_failure_clusters.csv` is:

| Cluster | Count |
|---|---:|
| Turn-delimiter runaway + syntax failure | 231 |
| Marker-free truncated code | 4 |
| Marker-free runnable wrong API | 3 |
| Marker-free parseable runtime failure | 1 |
| Turn-delimiter runaway but parseable | 1 |

### 2.6 Stability by seed and A/B order

| Seed | Physical order | B2 parse/run/target/oracle | B3 parse/run/target/oracle | B2 mean sec | B3 mean sec |
|---|---|---|---|---|---:|---:|
| 3407 | B2 then B3 | 65 / 64 / 48 / 43 | 2 / 1 / 0 / 0 | 18.319 | 19.044 |
| 7711 | B3 then B2 | 75 / 70 / 47 / 45 | 3 / 3 / 1 / 0 | 17.782 | 18.106 |

The severe B3 result is stable across both seeds and both observed physical orders. However, **order is perfectly confounded with seed** in this checkpoint: every seed-3407 pair is `B2_then_B3`, and every seed-7711 pair is `B3_then_B2`. There is no within-seed order variation, so an order effect cannot be separated from a seed effect. It is incorrect to claim that order has no effect; the evidence only shows failure under both confounded seed/order combinations.

B3 was slower than its paired B2 in 182/240 pairs. Mean paired difference was +0.524 seconds; median +0.479 seconds. This is descriptive and does not locate the cause.

### 2.7 Stability across all ten API groups

| API group | Pairs | B2 parse/run/target/oracle | B3 parse/run/target/oracle | B3 length |
|---|---:|---|---|---:|
| autograd_transform_compile_and_export | 24 | 11 / 11 / 4 / 4 | 0 / 0 / 0 / 0 | 24 |
| convolution_and_pooling | 24 | 14 / 14 / 0 / 0 | 3 / 2 / 0 / 0 | 24 |
| fft_and_spectral | 24 | 14 / 14 / 14 / 14 | 0 / 0 / 0 / 0 | 24 |
| indexing_gather_and_scatter | 24 | 13 / 13 / 13 / 13 | 1 / 1 / 1 / 0 | 24 |
| linear_algebra | 24 | 14 / 14 / 14 / 13 | 0 / 0 / 0 / 0 | 24 |
| normalization_activation_and_loss | 24 | 17 / 17 / 0 / 0 | 1 / 1 / 0 / 0 | 24 |
| reduction_and_statistics | 24 | 13 / 13 / 13 / 13 | 0 / 0 / 0 / 0 | 24 |
| shape_and_composition | 24 | 12 / 9 / 9 / 9 | 0 / 0 / 0 / 0 | 24 |
| sparse | 24 | 15 / 14 / 13 / 10 | 0 / 0 / 0 / 0 | 24 |
| tensor_creation | 24 | 17 / 15 / 15 / 12 | 0 / 0 / 0 / 0 | 24 |

The collapse is not isolated to one API family.

## 3. Frozen runner audit

### 3.1 Model loading and metadata

`runner/frozen_notebook_code.py` loads `Llama(...)` without an explicit `chat_format` or `chat_handler` and with `verbose=False`. The manifests record llama-cpp-python 0.3.23 but do not record:

- effective `llm.chat_format`;
- `tokenizer.chat_template` or its hash;
- BOS/EOS token ids and text;
- actual successful `(n_ctx, n_gpu_layers)` load attempt;
- completion token ids;
- response `usage`;
- generation branch.

The code tries load configurations `(2048,-1)`, `(2048,60)`, `(2048,48)`, `(1536,40)`, and `(1024,32)`. Events cannot reveal which attempt succeeded.

### 3.2 Primary chat path

Exact path:

```python
response = llm.create_chat_completion(messages=messages, **common)
raw = response['choices'][0]['message']['content']
```

`common` includes `max_tokens=600`, sampling settings, repeat penalty, and seed, but no explicit stop strings. Since no chat format is passed, llama-cpp-python chooses based on handler/format/GGUF metadata or fallback behavior. The effective choice was not logged.

### 3.3 Manual Gemma fallback

On `ValueError` or `RuntimeError`, the code calls:

```python
llm(manual_gemma_prompt(messages),
    stop=['<end_of_turn>', '<start_of_turn>'],
    echo=False, **common)
```

The fallback maps `assistant` to `model`, but emits a `system` role literally. Official Gemma instructions describe only `user` and `model` roles and say a separate system turn is unsupported. This is a real harness risk if fallback executes, but the evidence does not identify fallback events.

At least the 226 B3 outputs containing complete stop strings strongly indicate the primary path, assuming the fallback's documented text-stop behavior operated normally. The 14 outputs without complete delimiters remain branch-ambiguous; six of those contain truncated delimiter prefixes, bringing the delimiter/prefix phenotype to 232.

### 3.4 Extraction logic

`extract_python`:

1. selects the first complete fenced block if present;
2. otherwise trims everything before the first `import `;
3. preserves all later text.

This explains why generated subsequent chat turns become syntax errors. It is not evidence that extraction caused the model to generate the turns. Silently salvaging only the first turn would improve an evaluation metric while hiding the generation failure, so extraction should not be changed in the first diagnostic patch.

## 4. Ranked hypotheses

Only the required labels are used.

| Rank | Hypothesis | Label | Assessment |
|---:|---|---|---|
| 1 | Max-token exhaustion is the immediate termination mechanism | `directly_supported` | 240/240 `length`; all post-hoc counts 599–603 around cap 600; many raw tails are unfinished. It is not the initiating cause. |
| 2 | Repetitive/collapsed multi-turn output | `directly_supported` | 232/240 delimiter/prefix leakage, repeated role cycles, prompt echoes, and much higher n-gram repetition. This is an output phenotype. |
| 3 | Chat-template, stop-token, or EOS mismatch for B3 on the primary path | `plausible_but_unverified` | Best fit to continued generation after Gemma turn boundaries. Missing GGUF metadata/token ids and branch telemetry prevent proof. |
| 4 | GGUF conversion or merge mismatch | `plausible_but_unverified` | Could create an artifact-specific template/token-id mismatch, but source weights, merge logs, conversion command, and metadata are absent. |
| 5 | Quantization damage | `not_supported` | No higher-precision tuned control exists. B2 also uses Q3_K_M, so quantization level alone does not distinguish the failure. Artifact-specific damage is not ruled out. |
| 6 | Training collapse | `not_supported` | No training curves, checkpoints, adapter, tokenizer, or pre-GGUF inference are available. Collapsed output is not proof of collapsed training. |

## 5. Smallest safe harness patch

`proposed_runner.patch` does four narrowly scoped things on a copy of the runner:

1. supplies `['<end_of_turn>', '<start_of_turn>']` to the primary `create_chat_completion` path, matching the existing fallback stop policy;
2. records `generation_path` and fallback exception type;
3. records effective chat format, chat-template hash, EOS id, response usage, and whether stop text leaked;
4. changes `RUNNER_VERSION` to `four_baseline_runner_v1_b3diag_stop1`, guaranteeing a new run signature.

It does not touch old evidence, alter prompts, salvage/truncate old raw outputs, modify weights, or claim that the stop patch fixes the underlying artifact. It is designed to make the cheapest rerun diagnostic rather than silently overwrite the phenotype.

Apply only to a copy:

```bash
cp -a . /tmp/b3-package-test
patch -d /tmp/b3-package-test -p1 < proposed_runner.patch
```

Because the patch paths are rooted at `runner/`, an alternative from the package root is:

```bash
cp runner/frozen_notebook_code.py /tmp/frozen_notebook_code.py
patch -p1 --dry-run < proposed_runner.patch
```

Before model inference, dump and compare both GGUF metadata files if they become available:

```bash
python /path/to/llama.cpp/gguf-py/gguf/scripts/gguf_dump.py base.gguf > base.gguf.txt
python /path/to/llama.cpp/gguf-py/gguf/scripts/gguf_dump.py tuned.gguf > tuned.gguf.txt
diff -u base.gguf.txt tuned.gguf.txt
```

Specifically inspect `tokenizer.chat_template`, EOS/BOS ids, add-EOS flags, special-token tables, architecture, tensor names/shapes, and quantization metadata.

## 6. Cheap micro-rerun

The complete design, decision matrix, 60-minute hard budget, fixed crossed order, and stopping rule are in `MICRO_RERUN_PLAN.md`. It uses one API from each of all ten groups, both seeds, one fresh B2 control, and four B3 conditions to distinguish cap-only, explicit-stop, template-path, and artifact-level hypotheses without running a full campaign.

## 7. Reproducibility

Run all diagnostics:

```bash
python VALIDATE_PACKAGE.py
python b3_diagnostic.py
python -m unittest -v test_b3_diagnostic.py
```

Regenerate to alternate paths without touching evidence:

```bash
python b3_diagnostic.py \
  --package-root . \
  --json-out /tmp/b3_diagnostics.json \
  --clusters-out /tmp/b3_failure_clusters.csv
```

Important machine-readable locations:

- `b3_diagnostics.json#/validation`
- `b3_diagnostics.json#/baseline_summary`
- `b3_diagnostics.json#/b3_token_ceiling`
- `b3_diagnostics.json#/b3_endings_and_structure`
- `b3_diagnostics.json#/repetition_and_template_collapse`
- `b3_diagnostics.json#/pairwise`
- `b3_diagnostics.json#/runner_audit`
- `b3_diagnostics.json#/ranked_hypotheses`

## 8. Official documentation consulted — separate from empirical evidence

The following sources support only technical statements about the runtime, Gemma formatting, and GGUF metadata. All run-specific counts above come from uploaded files.

- **[W1] Version-pinned llama-cpp-python 0.3.23 source:** `https://github.com/abetlen/llama-cpp-python/blob/v0.3.23/llama_cpp/llama.py` — metadata chat-template selection, EOS handling, and tokenizer defaults.
- **[W2] Official llama-cpp-python README:** `https://github.com/abetlen/llama-cpp-python#chat-completion` — chat-handler/format/GGUF-template precedence and verbose format reporting.
- **[W3] Official llama-cpp-python API reference:** `https://llama-cpp-python.readthedocs.io/en/latest/api-reference/` — `stop` means strings that stop generation; `max_tokens` is the maximum number to generate. Current docs were used only as API documentation; [W1] is version-pinned for the run.
- **[W4] Official Google Gemma prompt structure:** `https://ai.google.dev/gemma/docs/core/prompt-structure` — `<start_of_turn>`, `<end_of_turn>`, `user`/`model`, and unsupported separate `system` role.
- **[W5] Official llama.cpp GGUF metadata definitions and tools:** `https://github.com/ggml-org/llama.cpp/blob/master/gguf-py/gguf/constants.py` and `https://github.com/ggml-org/llama.cpp/blob/master/gguf-py/README.md` — `tokenizer.chat_template` metadata key and `gguf_dump.py`.

## 9. Claim boundary

This review supports the statement:

> In the supplied two-seed checkpoint, the specific B3 GGUF/harness combination exhibits severe multi-turn/prompt-echo generation collapse, usually reaches the 600-token limit, and produces almost no valid test programs.

It does not support any of these stronger statements:

- the unavailable B3 weights are corrupt;
- fine-tuning caused the failure;
- Q3_K_M quantization caused the failure;
- the merge or GGUF conversion is defective;
- all fine-tuned models behave this way;
- the two-seed checkpoint is the planned five-seed final result.
