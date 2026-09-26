import argparse
import asyncio
import random
from datetime import UTC, datetime

import httpx


ROUTE_POINTS = [
    (55.7522, 37.6156),
    (55.7577, 37.6159),
    (55.7590, 37.6205),
]
VEHICLE_COUNT = 8


def position(progress: float) -> tuple[float, float, int]:
    scaled = progress * (len(ROUTE_POINTS) - 1)
    segment = min(int(scaled), len(ROUTE_POINTS) - 2)
    ratio = scaled - segment
    start, end = ROUTE_POINTS[segment], ROUTE_POINTS[segment + 1]
    lat = start[0] + (end[0] - start[0]) * ratio
    lon = start[1] + (end[1] - start[1]) * ratio
    nearest_stop = segment + 1 if ratio < 0.5 else segment + 2
    return lat, lon, nearest_stop


async def run(url: str, interval: float) -> None:
    sequence = 0
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            sequence += 1
            for index in range(VEHICLE_COUNT):
                progress = (sequence * 0.012 + index / VEHICLE_COUNT) % 1.0
                lat, lon, nearest_stop = position(progress)
                slow_vehicle = index in {1, 5}
                stopped = index == 3 and sequence % 8 in {0, 1}
                speed = random.uniform(3, 9) if slow_vehicle else random.uniform(17, 31)
                if stopped:
                    speed = 0.0
                payload = {
                    "vehicle_id": f"BUS-{100 + index}",
                    "route_id": 1,
                    "trip_id": "M2-001",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "speed": round(speed, 1),
                    "heading": 80 if progress < 0.5 else 65,
                    "nearest_stop_id": nearest_stop,
                    "door_status": "open" if stopped else "closed",
                }
                try:
                    response = await client.post(url, json=payload)
                    print(response.status_code, payload["vehicle_id"], flush=True)
                except httpx.HTTPError as exc:
                    print(f"stream retry: {exc}", flush=True)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.interval))
