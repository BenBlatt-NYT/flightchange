#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from src.export_charts import export_route_charts


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "data" / "flight-prices.csv"
DEFAULT_OUTPUT = ROOT / "data" / "charts"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export wide route CSVs for Excel line charts."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Source flight-prices.csv path",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for route-a.csv, route-b.csv, ...",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"Missing source CSV: {args.csv}")

    written = export_route_charts(args.csv, args.output_dir)
    for route_name, path in sorted(written.items()):
        row_count = sum(1 for _ in path.open()) - 1
        print(f"Route {route_name}: {path} ({row_count} rows)")


if __name__ == "__main__":
    main()
