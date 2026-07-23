# Validation-only failure case catalog

> Deterministic audit pointers, not additional observations or confirmed PyTorch bugs.

| Baseline | Failure category | API group | API | JSONL line | Exit | Evidence / diagnostic | Raw SHA-256 |
|---|---|---|---|---:|---:|---|---|
| B0 | `missing_oracle` | `tensor_creation` | `torch.tensor` | 1 | 0 | no recognized syntactic oracle | `87987932ac81` |
| B1 | `missing_oracle` | `tensor_creation` | `torch.tensor` | 121 | 0 | no recognized syntactic oracle | `e90349e71deb` |
| B1 | `wrong_or_missing_target_api` | `shape_and_composition` | `torch.permute` | 155 | 0 | no exact AST call matching torch.permute; near call tensor.permute (same terminal name on a different receiver) | `14aef248a026` |
| B1 | `shape_or_dtype_error` | `convolution_and_pooling` | `torch.nn.functional.conv_transpose1d` | 223 | 1 | matched runtime diagnostic /broadcast\|invalid for input of size\|expected input.*channel/; stderr: RuntimeError: Given transposed=1, weight of size [16, 8, 3], expected input[1, 8, 10] to have 16 channels, but got 8 channels instead | `6d41c92d3a57` |
| B1 | `undefined_name_error` | `convolution_and_pooling` | `torch.nn.functional.max_pool2d` | 231 | 1 | runtime NameError diagnostic; stderr: NameError: name 'de' is not defined | `e3b3e7d9e057` |
| B1 | `index_or_bounds_error` | `indexing_gather_and_scatter` | `torch.scatter` | 279 | 1 | runtime index/bounds diagnostic; stderr: IndexError: Dimension out of range (expected to be in range of [-1, 0], but got 1) | `361fad467e2a` |
| B1 | `argument_signature_error` | `indexing_gather_and_scatter` | `torch.index_put` | 286 | 1 | matched runtime diagnostic /argument .+ must be .+[, ]not /; stderr: TypeError: index_put(): argument 'indices' (position 1) must be tuple of Tensors, not Tensor | `cee2ca6fa176` |
| B1 | `runtime_error_other` | `sparse` | `torch.sparse_bsr_tensor` | 295 | 1 | nonzero exit without a recognized specific diagnostic or timeout; stderr: TypeError: 'torch.layout' object is not callable | `97a3dfb11559` |
| B1 | `broad_exception_swallowing` | `sparse` | `torch.sparse_bsc_tensor` | 297 | 0 | broad handler Exception has no re-raise | `92af1684a1bd` |
| B1 | `assertion_failure` | `autograd_transform_compile_and_export` | `torch.compile` | 358 | 1 | subprocess terminated with AssertionError; stderr: AssertionError | `97ccce83181c` |
| B2 | `oracle_not_executed` | `tensor_creation` | `torch.tensor` | 122 | 0 | oracle appears only on statically unreachable or uninvoked function path(s): test_torch_tensor_api | `2d8ce80c4800` |
| B2 | `target_not_executed` | `tensor_creation` | `torch.tensor` | 122 | 0 | target appears only on statically unreachable or uninvoked function path(s): test_torch_tensor_api | `2d8ce80c4800` |
| B2 | `truncated_generation` | `tensor_creation` | `torch.tensor` | 122 | 0 | finish_reason=length | `2d8ce80c4800` |
| B2 | `syntax_error` | `tensor_creation` | `torch.arange` | 128 | None | '[' was never closed (line 34) | `a462020cb20a` |
| B2 | `fake_assertion` | `tensor_creation` | `torch.zeros` | 133 | 0 | self-comparison assert | `524b73eeea63` |
| B2 | `assertion_failure` | `shape_and_composition` | `torch.reshape` | 146 | 1 | subprocess terminated with AssertionError; stderr: AssertionError | `b6b4caf8c096` |
| B2 | `missing_oracle` | `linear_algebra` | `torch.linalg.svd` | 212 | 0 | no recognized syntactic oracle | `6e737aafd374` |
| B3 | `syntax_error` | `tensor_creation` | `torch.tensor` | 361 | None | invalid syntax (line 12) | `d914034c4b13` |
| B3 | `truncated_generation` | `tensor_creation` | `torch.tensor` | 361 | None | finish_reason=length | `d914034c4b13` |
| B3 | `undefined_name_error` | `convolution_and_pooling` | `torch.nn.functional.conv_transpose1d` | 412 | 1 | runtime NameError diagnostic; stderr: NameError: name 'kernel' is not defined | `187229fa1644` |
| B3 | `missing_oracle` | `convolution_and_pooling` | `torch.nn.functional.conv_transpose1d` | 412 | 1 | no recognized syntactic oracle; stderr: NameError: name 'kernel' is not defined | `187229fa1644` |
| B3 | `target_not_executed` | `convolution_and_pooling` | `torch.nn.functional.conv_transpose1d` | 412 | 1 | target appears only on statically unreachable or uninvoked function path(s): test_conv_transpose1d; stderr: NameError: name 'kernel' is not defined | `187229fa1644` |

Use `source_sha256`, `source_record_index`, and the full `raw_output_sha256` in `failure_case_catalog.csv` to resolve each pointer against the immutable source snapshot.
