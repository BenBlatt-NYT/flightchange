from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .mcp_client import DEFAULT_MCP_URL, SkiplaggedMcpClient
from .parser import parse_cheapest_price
from .storage import TrackerStore


@dataclass
class Watch:
    id: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None = None
    flight_number: str | None = None
    preferred_airlines: list[str] | None = None
    direct_only: bool = True
    exclude_airlines: list[str] | None = None
    adults: int = 1
    max_stops: str | None = None
    sort: str = "price"
    limit: int = 5


@dataclass
class TrackerConfig:
    poll_interval_minutes: int
    request_delay_seconds: int
    watches: list[Watch]


@dataclass
class WatchResult:
    watch: Watch
    ok: bool
    message: str
    cheapest_price: float | None = None
    previous_price: float | None = None
    changed: bool = False


def load_config(path: Path) -> TrackerConfig:
    data = yaml.safe_load(path.read_text())
    watches = [
        Watch(
            id=item["id"],
            origin=item["origin"],
            destination=item["destination"],
            departure_date=item["departure_date"],
            return_date=item.get("return_date"),
            flight_number=item.get("flight_number"),
            preferred_airlines=item.get("preferred_airlines"),
            direct_only=item.get("direct_only", True),
            exclude_airlines=item.get("exclude_airlines"),
            adults=item.get("adults", 1),
            max_stops=item.get("max_stops"),
            sort=item.get("sort", "price"),
            limit=item.get("limit", 5),
        )
        for item in data["watches"]
    ]
    return TrackerConfig(
        poll_interval_minutes=int(data.get("poll_interval_minutes", 5)),
        request_delay_seconds=int(data.get("request_delay_seconds", 3)),
        watches=watches,
    )


def watch_to_arguments(watch: Watch) -> dict[str, Any]:
    args: dict[str, Any] = {
        "origin": watch.origin,
        "destination": watch.destination,
        "departureDate": watch.departure_date,
        "adults": watch.adults,
        "sort": watch.sort,
        "limit": watch.limit,
    }
    if watch.return_date:
        args["returnDate"] = watch.return_date
    if watch.max_stops:
        args["maxStops"] = watch.max_stops
    if watch.direct_only:
        args["includeHiddenCity"] = False
        args["includeVirtualInterlining"] = False
    if watch.preferred_airlines:
        args["preferredAirlines"] = watch.preferred_airlines
    elif watch.flight_number and len(watch.flight_number) >= 2 and not watch.direct_only:
        args["preferredAirlines"] = [watch.flight_number[:2].upper()]
    return args


class FlightTracker:
    def __init__(
        self,
        config: TrackerConfig,
        csv_path: Path,
        mcp_url: str = DEFAULT_MCP_URL,
        debug: bool = False,
    ) -> None:
        self.config = config
        self.client = SkiplaggedMcpClient(url=mcp_url)
        self.store = TrackerStore(csv_path=csv_path)
        self.mcp_url = mcp_url
        self.debug = debug

    def check_watch(self, watch: Watch, max_attempts: int = 3) -> WatchResult:
        arguments = watch_to_arguments(watch)
        if self.debug:
            print("--- request ---")
            print(f"MCP URL:     {self.mcp_url}")
            print("HTTP method: POST")
            print("Tool:        sk_flights_search")
            print(f"Arguments:   {arguments}")
            print(
                "Web equivalent: "
                f"https://skiplagged.com/flights/{watch.origin}/{watch.destination}/{watch.departure_date}"
            )
            if watch.flight_number:
                print(f"Trip anchor:    #{watch.flight_number}")

        response = None
        for attempt in range(1, max_attempts + 1):
            if self.debug and attempt > 1:
                print(f"Retry attempt: {attempt}/{max_attempts}")
            response = self.client.search_flights(arguments)
            if response.ok or "429" not in response.text:
                break
            if attempt < max_attempts:
                time.sleep(5 * attempt)

        assert response is not None
        if self.debug:
            print(f"HTTP status: 200 (from MCP server)")
            print(f"Tool error:  {response.is_error}")
            print(f"Response:    {response.text}")
            print("---------------")
        parsed = parse_cheapest_price(
            response.text,
            flight_number=watch.flight_number,
            direct_only=watch.direct_only,
            exclude_airlines=watch.exclude_airlines,
        )
        previous = self.store.latest_for_watch(watch.id)
        previous_price = previous.cheapest_price if previous else None

        if not response.ok:
            self.store.save_check(
                watch_id=watch.id,
                origin=watch.origin,
                destination=watch.destination,
                departure_date=watch.departure_date,
                flight_number=watch.flight_number,
                ok=False,
                error_text=response.text,
            )
            return WatchResult(
                watch=watch,
                ok=False,
                message=response.text,
                previous_price=previous_price,
            )

        if parsed.cheapest_price is None:
            message = parsed.summary or "No matching direct fare found"
            self.store.save_check(
                watch_id=watch.id,
                origin=watch.origin,
                destination=watch.destination,
                departure_date=watch.departure_date,
                flight_number=watch.flight_number,
                ok=False,
                error_text=message,
            )
            return WatchResult(
                watch=watch,
                ok=False,
                message=message,
                previous_price=previous_price,
            )

        changed = (
            previous_price is not None
            and parsed.cheapest_price is not None
            and parsed.cheapest_price != previous_price
        )

        self.store.save_check(
            watch_id=watch.id,
            origin=watch.origin,
            destination=watch.destination,
            departure_date=watch.departure_date,
            flight_number=watch.flight_number,
            ok=True,
            cheapest_price=parsed.cheapest_price,
        )

        if previous_price is None:
            message = f"Baseline price: ${parsed.cheapest_price:.2f}"
        elif changed:
            delta = parsed.cheapest_price - previous_price
            direction = "up" if delta > 0 else "down"
            message = (
                f"Price moved {direction}: ${previous_price:.2f} -> ${parsed.cheapest_price:.2f}"
            )
        else:
            message = f"No change: ${parsed.cheapest_price:.2f}"

        return WatchResult(
            watch=watch,
            ok=True,
            message=message,
            cheapest_price=parsed.cheapest_price,
            previous_price=previous_price,
            changed=changed,
        )

    def run_once(self) -> list[WatchResult]:
        results: list[WatchResult] = []
        for index, watch in enumerate(self.config.watches):
            result = self.check_watch(watch)
            results.append(result)
            if index < len(self.config.watches) - 1:
                time.sleep(self.config.request_delay_seconds)
        return results

    def run_forever(self) -> None:
        interval_seconds = self.config.poll_interval_minutes * 60
        print(
            f"Tracking {len(self.config.watches)} watches every "
            f"{self.config.poll_interval_minutes} minutes "
            f"({self.config.request_delay_seconds}s between requests)."
        )

        while True:
            started = time.time()
            results = self.run_once()
            for result in results:
                prefix = "CHANGE" if result.changed else ("ERROR" if not result.ok else "OK")
                route = (
                    f"{result.watch.origin}->{result.watch.destination} "
                    f"({result.watch.departure_date})"
                )
                print(f"[{prefix}] {result.watch.id} {route}: {result.message}")

            elapsed = time.time() - started
            sleep_for = max(0, interval_seconds - elapsed)
            time.sleep(sleep_for)
