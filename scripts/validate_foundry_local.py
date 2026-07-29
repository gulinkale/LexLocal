"""Validate Foundry Local model inference on the development machine."""

from foundry_local_sdk import Configuration, FoundryLocalManager

MODEL_ALIAS = "qwen2.5-0.5b"


def main() -> None:
    """Download, load, query, and unload a local model."""

    print("Initializing Foundry Local...")

    configuration = Configuration(app_name="lexlocal")
    FoundryLocalManager.initialize(configuration)
    manager = FoundryLocalManager.instance

    print("Preparing execution providers...")
    manager.download_and_register_eps()

    print(f"Selecting model: {MODEL_ALIAS}")
    model = manager.catalog.get_model(MODEL_ALIAS)

    print("Downloading model...")
    model.download(
        lambda progress: print(
            f"\rDownload progress: {progress:.2f}%",
            end="",
            flush=True,
        )
    )
    print()

    try:
        print("Loading model...")
        model.load()

        client = model.get_chat_client()

        messages = [
            {
                "role": "user",
                "content": (
                    "Reply with exactly one short sentence confirming "
                    "that local inference works."
                ),
            }
        ]

        print("Model response: ", end="", flush=True)

        for chunk in client.complete_streaming_chat(messages):
            if not chunk.choices:
                continue

            content = chunk.choices[0].delta.content
            if content:
                print(content, end="", flush=True)

        print()

    finally:
        print("Unloading model...")
        model.unload()

    print("Foundry Local validation completed successfully.")


if __name__ == "__main__":
    main()