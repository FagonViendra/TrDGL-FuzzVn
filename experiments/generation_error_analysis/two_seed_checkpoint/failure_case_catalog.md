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
| B0 | `missing_oracle` | `tensor_creation` | `torch.tensor` | 1 | 0 | no recognized syntactic oracle | `65256390c579` |
| B1 | `missing_oracle` | `tensor_creation` | `torch.tensor` | 241 | 0 | no recognized syntactic oracle | `97aa8de59d05` |
| B1 | `wrong_or_missing_target_api` | `shape_and_composition` | `torch.permute` | 276 | 0 | no exact AST call matching torch.permute; near call tensor.permute (same terminal name on a different receiver) | `3af684f1d81a` |
| B1 | `argument_signature_error` | `indexing_gather_and_scatter` | `torch.index_put` | 405 | 1 | matched runtime diagnostic /argument .+ must be .+[, ]not /; stderr: TypeError: index_put_(): argument 'indices' (position 1) must be tuple of Tensors, not Tensor | `b4a7d870f1f2` |
| B1 | `runtime_error_other` | `sparse` | `torch.sparse_bsr_tensor` | 415 | 1 | nonzero exit without a recognized specific diagnostic or timeout; stderr: TypeError: 'torch.layout' object is not callable | `1f21a6ec7f1a` |
| B1 | `broad_exception_swallowing` | `sparse` | `torch.sparse_bsc_tensor` | 417 | 0 | broad handler Exception has no re-raise | `a5143aebef71` |
| B1 | `shape_or_dtype_error` | `sparse` | `torch.sparse.spdiags` | 429 | 1 | matched runtime diagnostic /\bshape\b\|size mismatch\|sizes? of tensors? must match\|size of tensor .* must match/; stderr: TypeError: _spdiags() missing 1 required positional arguments: "shape" | `41bbdde8ba4e` |
| B2 | `oracle_not_executed` | `tensor_creation` | `torch.tensor` | 242 | 0 | oracle appears only on statically unreachable or uninvoked function path(s): test_torch_tensor_api | `ccd804519d40` |
| B2 | `target_not_executed` | `tensor_creation` | `torch.tensor` | 242 | 0 | target appears only on statically unreachable or uninvoked function path(s): test_torch_tensor_api | `ccd804519d40` |
| B2 | `truncated_generation` | `tensor_creation` | `torch.tensor` | 242 | 0 | finish_reason=length | `ccd804519d40` |
| B2 | `syntax_error` | `tensor_creation` | `torch.as_tensor` | 243 | None | invalid syntax (line 41) | `f9a8d1e7dcc7` |
| B2 | `runtime_error_other` | `tensor_creation` | `torch.from_numpy` | 246 | 1 | nonzero exit without a recognized specific diagnostic or timeout; stderr: TypeError: can't assign a numpy.float32 to a torch.FloatTensor | `5a0b3c281e2a` |
| B2 | `fake_assertion` | `tensor_creation` | `torch.zeros` | 254 | 0 | self-comparison assert | `8b30fea802a1` |
| B2 | `assertion_failure` | `shape_and_composition` | `torch.reshape` | 266 | 1 | subprocess terminated with AssertionError; stderr: AssertionError: Reshape failed on non-contiguous input | `ee6ad3c04985` |
| B2 | `undefined_name_error` | `shape_and_composition` | `torch.unsqueeze` | 272 | 1 | runtime NameError diagnostic; stderr: NameError: name 'test' is not defined | `f8a671c03d30` |
| B2 | `wrong_or_missing_target_api` | `sparse` | `torch.sparse_bsc_tensor` | 418 | 0 | no exact AST call matching torch.sparse_bsc_tensor | `2439759530df` |
| B2 | `missing_oracle` | `sparse` | `torch.sparse_bsc_tensor` | 418 | 0 | no recognized syntactic oracle | `2439759530df` |
| B2 | `broad_exception_swallowing` | `autograd_transform_compile_and_export` | `torch.compile` | 478 | 0 | broad handler Exception has no re-raise | `e1f29d74acb0` |
| B3 | `syntax_error` | `tensor_creation` | `torch.tensor` | 121 | None | invalid syntax (line 17) | `460009b3c5d6` |
| B3 | `truncated_generation` | `tensor_creation` | `torch.tensor` | 121 | None | finish_reason=length | `460009b3c5d6` |
| B3 | `missing_oracle` | `convolution_and_pooling` | `torch.nn.functional.max_pool2d` | 176 | 0 | no recognized syntactic oracle | `ef77b7f3ad0d` |
| B3 | `target_not_executed` | `normalization_activation_and_loss` | `torch.nn.functional.group_norm` | 183 | 0 | target appears only on statically unreachable or uninvoked function path(s): test_group_norm | `659606416509` |

Use `source_sha256`, `source_record_index`, and the full `raw_output_sha256` in `failure_case_catalog.csv` to resolve each pointer against the immutable source snapshot.
