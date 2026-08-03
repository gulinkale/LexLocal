# Foundry Local Validation

## Objective

FOUNDRY-001 validates that Microsoft Foundry Local can load a supported model
and return meaningful chat content through Python on the development machine.
This is an M0 runtime smoke validation, not the production model integration.

## Model Roles

- **M0 validation model:** `qwen2.5-0.5b`
- **Future production candidates:** aliases such as `qwen3-4b` and the embedding
  model in `release/release_manifest.yaml` remain unverified candidates. They
  are not validated by this M0 check.

## Validation Environment

| Field | Recorded value |
|---|---|
| Validation date | 2026-08-02 |
| Operating system | macOS / Darwin 24.6.0 |
| Architecture | Apple Silicon (`arm64`) |
| Python | 3.11.15 |
| Foundry Local SDK | 1.2.3 |
| Requested alias | `qwen2.5-0.5b` |
| Resolved model identity | `qwen2.5-0.5b-instruct-generic-gpu:4` |
| Execution provider | `WebGpuExecutionProvider` |

The validation script prints these non-sensitive environment and resolved-model
fields when the installed SDK exposes them.

## Commands

Prepare execution providers and the model while online:

```bash
uv run python scripts/validate_foundry_local.py --model qwen2.5-0.5b
```

Then perform a strict offline cached rerun:

1. Disconnect Wi-Fi/Ethernet or otherwise disable network access. On macOS, a
   reproducible process-level alternative is:

   ```bash
   sandbox-exec -p '(version 1) (allow default) (deny network*)' \
     uv run python scripts/validate_foundry_local.py \
     --model qwen2.5-0.5b \
     --cached-only
   ```

2. Without the macOS wrapper, run the following only after manually disabling
   network access:

   ```bash
   uv run python scripts/validate_foundry_local.py \
     --model qwen2.5-0.5b \
     --cached-only
   ```

3. Confirm the output reports cached mode, the resolved identity/provider, and
   `Meaningful assistant content received: yes`.

SDK 1.2.3 exposes `model.is_cached`, but no API that proves the operating system
is offline. `--cached-only` requires the local cache and skips intentional
execution-provider and model downloads. Physical network disconnection is still
required for strict offline evidence.

## Success Criteria

A validation run succeeds only when:

- the requested alias resolves,
- cached-only mode finds the model in the local cache,
- the model loads successfully,
- streaming returns non-whitespace assistant content,
- the script reports meaningful content and exits with status 0,
- and the loaded model is unloaded afterward.

Empty streams, chunks without choices/content, whitespace-only content, lookup
failures, preparation failures, load failures, and streaming failures must not
produce the final success message.

## Sanitized Current Result

### Online preparation — passed on 2026-08-02

Sanitized result:

```text
Validation mode: online preparation
Python version: 3.11.15
Foundry Local SDK version: 1.2.3
Operating system: Darwin 24.6.0
Machine architecture: arm64
Requested model alias: qwen2.5-0.5b
Resolved model identity: qwen2.5-0.5b-instruct-generic-gpu:4
Execution provider: WebGpuExecutionProvider
Meaningful assistant content received: yes
Unloading model...
Foundry Local validation completed successfully.
```

The process exited successfully. The response text and local cache paths are not
recorded.

### Cached-only path — passed on 2026-08-02

The cached-only command succeeded, skipped intentional execution-provider/model
downloads, received meaningful content, unloaded the model, and exited with
status 0. Network access was still available during this run, so it validates
the cache-only code path but is **not** strict offline evidence.

### Offline cached inference

**Passed on 2026-08-02 at 16:22:35 +03:00.** The process ran under macOS
`sandbox-exec` with `(deny network*)`, which explicitly denied network access.

Sanitized result:

```text
Validation mode: cached-only (network state not verified by the script itself)
Python version: 3.11.15
Foundry Local SDK version: 1.2.3
Operating system: Darwin 24.6.0
Machine architecture: arm64
Requested model alias: qwen2.5-0.5b
Execution-provider download preparation: skipped in cached-only mode
Resolved model identity: qwen2.5-0.5b-instruct-generic-gpu:4
Execution provider: WebGpuExecutionProvider
Model download: skipped; cached model required
Meaningful assistant content received: yes
Unloading model...
Foundry Local validation completed successfully.
```

The command exited with status 0. Network denial was enforced by the external
macOS sandbox profile rather than by Foundry Local SDK 1.2.3.

## Known Limitations

- Initial runtime, execution-provider, and model preparation requires internet.
- Performance depends on the selected model and available device memory.
- Current hardware evidence is limited to the recorded Apple Silicon machine.
- The script uses a fixed synthetic, non-sensitive prompt.
- This validation does not cover RAG, embeddings, document ingestion, PDF/OCR,
  legal question answering, production lifecycle management, or PySide6 UI
  integration.
