"""
EdgeX Foundry READ-ONLY MCP server (for the Hermes "comms" profile).

Exposes: list_devices, device_status, offline_devices, latest_readings.
No write tools on purpose -- the control agent gets a separate server.

Install:  pip install "mcp[cli]" httpx
Run:      python edgex_readonly_mcp.py        (stdio; Hermes launches it)

Env vars (defaults assume EdgeX 3.x/4.x in non-secure mode on localhost):
  EDGEX_METADATA_URL   http://localhost:59881
  EDGEX_DATA_URL       http://localhost:59880
  EDGEX_TOKEN          optional bearer token (secure mode / API gateway)
  EDGEX_STALE_SECONDS  a device is "inactive" if its newest reading is older (default 60)
"""
import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

METADATA = os.getenv("EDGEX_METADATA_URL", "http://localhost:59881").rstrip("/")
DATA = os.getenv("EDGEX_DATA_URL", "http://localhost:59880").rstrip("/")
TOKEN = os.getenv("EDGEX_TOKEN")
STALE_S = float(os.getenv("EDGEX_STALE_SECONDS", "60"))

HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
mcp = FastMCP("edgex-readonly")


def _get(url: str, params: dict | None = None) -> dict:
    r = httpx.get(url, params=params, headers=HEADERS, timeout=5.0)
    r.raise_for_status()
    return r.json()


def _all_devices() -> list[dict]:
    body = _get(f"{METADATA}/api/v3/device/all", {"limit": -1})
    return body.get("devices", [])


def _latest_reading(device: str) -> dict | None:
    body = _get(f"{DATA}/api/v3/reading/device/name/{device}", {"limit": 1})
    readings = body.get("readings") or []
    return readings[0] if readings else None


def _status(dev: dict) -> dict:
    """Combine EdgeX states with last-reading age into one status record."""
    name = dev["name"]
    try:
        last = _latest_reading(name)
    except httpx.HTTPError:
        last = None
    age_s = None
    if last and last.get("origin"):
        age_s = round(time.time() - last["origin"] / 1e9, 1)  # origin is in ns
    active = (
        dev.get("adminState") == "UNLOCKED"
        and dev.get("operatingState") == "UP"
        and age_s is not None
        and age_s <= STALE_S
    )
    return {
        "name": name,
        "type": dev.get("profileName"),
        "service": dev.get("serviceName"),
        "adminState": dev.get("adminState"),
        "operatingState": dev.get("operatingState"),
        "lastReadingAgeSeconds": age_s,
        "active": active,
    }


@mcp.tool()
def list_devices() -> list[dict]:
    """List all EdgeX devices with their type (device profile) and service."""
    return [
        {"name": d["name"], "type": d.get("profileName"), "service": d.get("serviceName"),
         "labels": d.get("labels", [])}
        for d in _all_devices()
    ]


@mcp.tool()
def device_status(name: str) -> dict:
    """Active/inactive status for one device, with the reason fields."""
    for d in _all_devices():
        if d["name"] == name:
            return _status(d)
    return {"error": f"device '{name}' not found"}


@mcp.tool()
def offline_devices() -> list[dict]:
    """All devices currently considered inactive."""
    return [s for s in (_status(d) for d in _all_devices()) if not s["active"]]


@mcp.tool()
def latest_readings(name: str, limit: int = 5) -> list[dict]:
    """Most recent readings for a device (max 50)."""
    body = _get(f"{DATA}/api/v3/reading/device/name/{name}", {"limit": max(1, min(limit, 50))})
    return [
        {"resource": r.get("resourceName"), "value": r.get("value"),
         "valueType": r.get("valueType"), "origin": r.get("origin")}
        for r in body.get("readings", [])
    ]


if __name__ == "__main__":
    mcp.run()  # stdio transport