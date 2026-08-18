from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CSV_FIELDS = [
    "checked_at",
    "route_name",
    "watch_id",
    "origin",
    "destination",
    "departure_date",
    "flight_number",
    "airline",
    "departure_local",
    "price",
    "ok",
    "error",
]


@dataclass
class LatestSnapshot:
    watch_id: str
    checked_at: str
    cheapest_price: float | None


class TrackerStore:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
                writer.writeheader()

    def save_check(
        self,
        watch_id: str,
        route_name: str,
        origin: str,
        destination: str,
        departure_date: str,
        flight_number: str | None,
        ok: bool,
        cheapest_price: float | None = None,
        error_text: str | None = None,
        airline: str | None = None,
        departure_local: str | None = None,
        checked_at: str | None = None,
    ) -> None:
        row = {
            "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
            "route_name": route_name,
            "watch_id": watch_id,
            "origin": origin,
            "destination": destination,
            "departure_date": departure_date,
            "flight_number": flight_number or "",
            "airline": airline or "",
            "departure_local": departure_local or "",
            "price": "" if cheapest_price is None else f"{cheapest_price:.2f}",
            "ok": "1" if ok else "0",
            "error": error_text or "",
        }
        with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writerow(row)

    def latest_for_watch(self, watch_id: str) -> LatestSnapshot | None:
        latest: LatestSnapshot | None = None
        with self.csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["watch_id"] != watch_id or row["ok"] != "1":
                    continue
                price = row["price"].strip()
                latest = LatestSnapshot(
                    watch_id=row["watch_id"],
                    checked_at=row["checked_at"],
                    cheapest_price=float(price) if price else None,
                )
        return latest

    def latest_for_flight(self, route_watch_id: str, flight_number: str) -> LatestSnapshot | None:
        """Latest successful price for a flight under a route-scan watch."""
        target = flight_number.upper()
        latest: LatestSnapshot | None = None
        with self.csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["watch_id"] != route_watch_id or row["ok"] != "1":
                    continue
                if (row.get("flight_number") or "").upper() != target:
                    continue
                price = row["price"].strip()
                latest = LatestSnapshot(
                    watch_id=row["watch_id"],
                    checked_at=row["checked_at"],
                    cheapest_price=float(price) if price else None,
                )
        return latest
