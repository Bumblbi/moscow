import argparse
import asyncio
import random
from datetime import UTC, datetime

import httpx


async def run(url: str, interval: float) -> None:
    sequence = 0
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            sequence += 1
            payload = {
                "vehicle_id": "BUS-100",
                "route_id": 1,
                "trip_id": "M2-001",
                "timestamp": datetime.now(UTC).isoformat(),
                "lat": 55.7522 + sequence * 0.0002,
                "lon": 37.6156 + sequence * 0.0002,
                "speed": round(random.uniform(5, 30), 1),
                "heading": 80,
                "nearest_stop_id": min(3, 1 + sequence // 10),
                "door_status": "open" if sequence % 12 == 0 else "closed",
            }
            try:
                response = await client.post(url, json=payload)
                print(response.status_code, response.text, flush=True)
            except httpx.HTTPError as exc:
                print(f"stream retry: {exc}", flush=True)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.interval))
