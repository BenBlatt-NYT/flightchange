from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _cluster_gap() -> timedelta:
    """Max gap between checks in the same polling batch."""
    return timedelta(seconds=90)


def export_route_charts(
    source_csv: Path,
    output_dir: Path,
    *,
    batch_gap_seconds: int = 90,
) -> dict[str, Path]:
    """Pivot flight-prices.csv into one wide CSV per route for Excel line charts."""
    rows_by_route: dict[str, list[dict[str, str]]] = defaultdict(list)
    with source_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["ok"] != "1" or not row["price"].strip():
                continue
            rows_by_route[row["route_name"]].append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    gap = timedelta(seconds=batch_gap_seconds)
    written: dict[str, Path] = {}

    for route_name in sorted(rows_by_route):
        route_rows = sorted(
            rows_by_route[route_name],
            key=lambda row: _parse_time(row["checked_at"]),
        )
        flights = sorted({row["flight_number"] for row in route_rows if row["flight_number"]})
        batches: list[tuple[datetime, dict[str, str]]] = []

        current_start: datetime | None = None
        current_last: datetime | None = None
        current_prices: dict[str, str] = {}

        def flush_batch() -> None:
            nonlocal current_start, current_last, current_prices
            if current_start is None or not current_prices:
                return
            batches.append((current_start, dict(current_prices)))
            current_start = None
            current_last = None
            current_prices = {}

        for row in route_rows:
            checked_at = _parse_time(row["checked_at"])
            flight_number = row["flight_number"]
            if not flight_number:
                continue

            if current_start is None:
                current_start = checked_at
                current_last = checked_at
                current_prices = {flight_number: row["price"]}
                continue

            if checked_at - current_last > gap:
                flush_batch()
                current_start = checked_at
                current_last = checked_at
                current_prices = {flight_number: row["price"]}
                continue

            current_last = checked_at
            current_prices[flight_number] = row["price"]

        flush_batch()

        output_path = output_dir / f"route-{route_name.lower()}.csv"
        fieldnames = ["checked_at", *flights]
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for batch_time, prices in batches:
                out_row = {"checked_at": _format_time(batch_time)}
                for flight in flights:
                    out_row[flight] = prices.get(flight, "")
                writer.writerow(out_row)

        written[route_name] = output_path

    return written
