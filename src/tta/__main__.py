"""Uvicorn entrypoint — run with ``python -m tta``."""

import uvicorn


def main() -> None:
    """Start the TTA server via uvicorn with app-factory mode."""
    uvicorn.run(
        "tta.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
    )


if __name__ == "__main__":
    main()
