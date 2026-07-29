# Foundry Local Validation

## Purpose

This document records the validation of Foundry Local for the LexLocal desktop
application.

## Development Environment

- Platform: macOS
- Architecture: Apple Silicon (`arm64`)
- Python: 3.11.15
- Integration: `foundry-local-sdk`
- Validation script: `scripts/validate_foundry_local.py`

## Validation Steps

1. Installed the Foundry Local Python SDK with `uv`.
2. Initialized the Foundry Local runtime from Python.
3. Selected and downloaded a supported local model.
4. Loaded the model into memory.
5. Sent a simple inference request from Python.
6. Received a valid model response.
7. Unloaded the model after inference.
8. Repeated the inference test without an internet connection.

## Result

Foundry Local inference works successfully on the development machine.

After the model and required runtime components are downloaded, inference can
run locally without sending prompts or model responses to an external API.

## Current Scope

This validation confirms only basic local model inference.

The following features are not included yet:

- Retrieval-augmented generation
- Embeddings
- Document ingestion
- PDF processing
- OCR
- Legal question answering
- PySide6 user-interface integration

## Known Limitations

- Initial model and runtime downloads require an internet connection.
- Model performance depends on the selected model and available device memory.
- This validation uses a fixed non-sensitive test prompt.
- Application-level model lifecycle and error handling will be implemented
  during later integration work.