from __future__ import annotations
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

SAMPLE_HELLO = {
    "protocol_version": "CNPv1",
    "message_type": "hello",
    "message_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    "node_id": "cnp-office-climate-01",
    "ts_utc": "2026-03-18T10:21:00Z",
    "qos": 1,
    "payload": {
        "device_uid": "ab12cd34ef56",
        "node_name": "Office Climate 01",
        "node_type": "sensor",
        "firmware_version": "0.1.0",
        "hardware_model": "esp32-c3-supermini",
        "capabilities": {"sensors": ["temperature"], "actuators": [], "connectivity": ["wifi"]},
        "supports_ota": True,
        "boot_reason": "power_on",
    },
}

def main() -> int:
    schema_doc = (BASE / "docs" / "schemas" / "cnp_v1_message_schema.md").read_text(encoding="utf-8")
    required_terms = ["hello", "heartbeat", "command", "error", "protocol_version", "node_id"]
    missing = [term for term in required_terms if term not in schema_doc]
    if missing:
        print("Missing schema terms:", missing)
        return 1
    print("Schema doc contains required terms.")
    print("Sample hello envelope:")
    print(json.dumps(SAMPLE_HELLO, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
