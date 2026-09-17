"""
EdgeX Foundry READ-ONLY MCP server for Q-PRIME.

Tools: list_devices, device_status, offline_devices, latest_readings.
No write tools on purpose -- device control will get a separate server.

Works with any MCP client: Claude Code / Claude Desktop, Codex, Hermes,
and Ollama models via an MCP client such as ollmcp. See README.md.

Transports (MCP_TRANSPORT):
  stdio            default; the client launches the process (python or `docker run -i`)
  streamable-http  long-running server at http://<host>:<port>/mcp (Docker Compose mode)

Env vars:
  EDGEX_METADATA_URL   http://localhost:59881
  EDGEX_DATA_URL       http://localhost:59880
  EDGEX_TOKEN          optional bearer token for EdgeX (secure mode / API gateway)
  EDGEX_STALE_SECONDS  device is "inactive" if its newest reading is older (default 60)
  MCP_TRANSPORT        stdio | streamable-http            (default stdio)
  MCP_HOST             bind address for HTTP              (default 127.0.0.1)
  MCP_PORT             port for HTTP                      (default 8765)
  MCP_AUTH_TOKEN       if set, HTTP clients must send "Authorization: Bearer <token>"

Requires mcp<2 (mcp 2.x renamed FastMCP).
"""
import hmac
import logging
import os
import sys
import time

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

METADATA = os.getenv("EDGEX_METADATA_URL", "http://localhost:59881").rstrip("/")
DATA = os.getenv("EDGEX_DATA_URL", "http://localhost:59880").rstrip("/")
TOKEN = os.getenv("EDGEX_TOKEN")
STALE_S = float(os.getenv("EDGEX_STALE_SECONDS", "60"))

TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
HOST = os.getenv("MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_PORT", "8765"))
AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN")

HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
logging.getLogger("httpx").setLevel(logging.WARNING)  # keep per-request logs quiet

mcp = FastMCP(
    "edgex-readonly",
    instructions=(
        "Read-only view of EdgeX Foundry devices in the Q-PRIME stack. "
        "A device's 'type' is its EdgeX device profile. 'active' means the device is "
        "UNLOCKED, operatingState UP, and has a reading newer than the stale threshold."
    ),
    host=HOST,
    port=PORT,
)


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


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    """Liveness for Docker; also reports whether EdgeX core-metadata answers."""
    try:
        edgex_ok = httpx.get(f"{METADATA}/api/v3/ping", headers=HEADERS, timeout=2.0).is_success
    except httpx.HTTPError:
        edgex_ok = False
    return JSONResponse({"status": "ok", "edgex": edgex_ok})


class BearerAuth:
    """Minimal ASGI guard: every path except /health needs the shared token."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path") != "/health":
            auth = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not hmac.compare_digest(auth, b"Bearer " + self.token):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def main() -> None:
    if TRANSPORT == "stdio":
        mcp.run("stdio")
    elif TRANSPORT == "streamable-http":
        if not AUTH_TOKEN:
            mcp.run("streamable-http")
            return
        import uvicorn

        uvicorn.run(BearerAuth(mcp.streamable_http_app(), AUTH_TOKEN), host=HOST, port=PORT)
    else:
        sys.exit(f"Unknown MCP_TRANSPORT '{TRANSPORT}' (use stdio or streamable-http)")


if __name__ == "__main__":
    main()
