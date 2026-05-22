"""Application entry point."""

from __future__ import annotations

import sys

from kinatio.app import KinatioApp
from kinatio.cli import main as cli_main


def run_tui() -> int:
    """Run the Textual application."""

    app = KinatioApp()
    app.run()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Route between the default TUI and the CLI surface."""

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return run_tui()
    if args[0] in {"tui", "--tui"}:
        return run_tui()
    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
