from __future__ import annotations
import statistics
import time

def benchmark_json_roundtrip(iterations: int = 10000) -> None:
    import json
    sample = {
        "protocol_version": "CNPv1",
        "message_type": "event",
        "message_id": "bench-0001",
        "node_id": "cnp-bench-01",
        "ts_utc": "2026-03-18T10:21:00Z",
        "qos": 1,
        "payload": {
            "event_type": "temperature_reading",
            "category": "telemetry",
            "priority": "normal",
            "delivery_mode": "fire_and_forget",
            "requires_ack": False,
            "event_seq": 1,
            "body": {"temperature_c": 24.8}
        }
    }
    timings = []
    for _ in range(iterations):
        start = time.perf_counter()
        encoded = json.dumps(sample)
        _ = json.loads(encoded)
        timings.append((time.perf_counter() - start) * 1e6)
    print(f"Iterations: {iterations}")
    print(f"Mean us/op: {statistics.mean(timings):.2f}")
    print(f"P95 us/op: {statistics.quantiles(timings, n=20)[18]:.2f}")

if __name__ == "__main__":
    benchmark_json_roundtrip()
