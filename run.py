#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from src.tracker import FlightTracker, load_config


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "watches.yaml"
DEFAULT_CSV = ROOT / "data" / "tracker.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Track Skiplagged flight prices via the public MCP server."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to watches.yaml",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="CSV file path for price history",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one polling cycle and exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print the MCP URL, tool name, and request payload before each call",
    )
    args = parser.parse_args()

    if not args.config.exists():
        example = ROOT / "config" / "watches.example.yaml"
        raise SystemExit(
            f"Missing config file: {args.config}\n"
            f"Copy {example} to {args.config} and add your watches."
        )

    config = load_config(args.config)
    tracker = FlightTracker(config=config, csv_path=args.csv, debug=args.debug)

    if args.once:
        for result in tracker.run_once():
            prefix = "CHANGE" if result.changed else ("ERROR" if not result.ok else "OK")
            print(f"[{prefix}] {result.watch.id}: {result.message}")
        return

    tracker.run_forever()


if __name__ == "__main__":
    main()
