"""CLI entry point (`due`): argument parsing, signals, app startup, teardown."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Callable

from openbrightness.due.capture.base import CaptureError, DisplayCaptureBackend
from openbrightness.due.capture.mock import MockCaptureBackend
from openbrightness.due.capture.wlr import WlrScreencopyBackend
from openbrightness.due.discovery import DiscoveryError, find_output, list_outputs
from openbrightness.due.models import OutputInfo

log = logging.getLogger(__name__)

BACKEND_CHOICES = ("auto", "wlr", "mock")


def build_backend_factory(
    backend_name: str,
) -> Callable[[OutputInfo], DisplayCaptureBackend]:
    def factory(output: OutputInfo) -> DisplayCaptureBackend:
        if backend_name == "mock":
            return MockCaptureBackend(output, fps=1.0)
        return WlrScreencopyBackend(output, fps=1.0)

    return factory


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="due",
        description="OpenBrightness Display Understanding Engine — read-only display analysis",
    )
    parser.add_argument(
        "--display",
        metavar="CONNECTOR",
        help="capture this output (e.g. eDP-1); omit for the interactive picker",
    )
    parser.add_argument(
        "--backend",
        choices=BACKEND_CHOICES,
        default="auto",
        help="capture backend (default: auto = wlr, mock via explicit choice)",
    )
    parser.add_argument(
        "--list-outputs",
        action="store_true",
        help="enumerate active outputs and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug logging on stderr",
    )
    return parser.parse_args(argv)


def _resolve_outputs(display: str | None) -> tuple[list[OutputInfo], OutputInfo | None]:
    outputs = list_outputs()
    if display is None:
        return outputs, None
    found = find_output(display, outputs)
    if found is None:
        names = ", ".join(o.connector for o in outputs)
        raise CaptureError(f"output {display!r} not found; available: {names}")
    return outputs, found


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        outputs, initial = _resolve_outputs(args.display)
    except DiscoveryError as exc:
        print(f"due: {exc}", file=sys.stderr)
        return 1
    except CaptureError as exc:
        print(f"due: {exc}", file=sys.stderr)
        return 1

    if args.list_outputs:
        for output in outputs:
            marker = "*" if output.is_primary else " "
            print(f"{marker} {output.connector:<12} {output.label}")
        return 0

    from openbrightness.due.tui.app import DueApp

    app = DueApp(
        outputs=outputs,
        backend_factory=build_backend_factory(args.backend),
        initial_output=initial,
    )

    def _forward_signal(signum: int, _frame: object) -> None:
        log.debug("signal %d received, exiting", signum)
        app.call_from_thread(app.exit)

    signal.signal(signal.SIGTERM, _forward_signal)
    signal.signal(signal.SIGINT, _forward_signal)

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
