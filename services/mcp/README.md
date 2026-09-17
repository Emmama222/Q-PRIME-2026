# EdgeX MCP server (read-only)

Lets AI assistants see the EdgeX devices in the Q-PRIME stack: what devices
exist, what type each is, whether each is active, and its latest readings.

It has **no write tools**. Device control will be a separate server with its
own allowlist.

| Tool | Returns |
|---|---|
| `list_devices` | Every device with its type (EdgeX device profile) and device service |
| `device_status` | One device's status: `adminState`, `operatingState`, age of its last reading, `active` |
| `offline_devices` | Every device that is currently inactive |
| `latest_readings` | The newest readings for one device (up to 50) |

A device counts as **active** when all three are true:

- it is `UNLOCKED`;
- its `operatingState` is `UP`;
- it has a reading newer than `EDGEX_STALE_SECONDS` (default 60).

The default suits the Sample EdgeX Feed at 60 records a minute. If you lower
`QPRIME_SAMPLE_RATE_PER_MIN`, raise the threshold.

## Run it

The server is part of the `edgex` profile:

```bash
docker compose --profile edgex up -d --build
curl http://localhost:8765/health        # {"status":"ok","edgex":true}
```

The MCP endpoint is **`http://localhost:8765/mcp`** (streamable HTTP). It
listens on `127.0.0.1` only.

To require a token, set `QPRIME_MCP_TOKEN` in `.env`. Clients then have to send
`Authorization: Bearer <token>`. `/health` stays open.

## Connect a client

### Claude Code

The repo-root `.mcp.json` already points at the server. Open the repo in
Claude Code and approve the `qprime-edgex` server when prompted. To add it by
hand instead:

```bash
claude mcp add --transport http qprime-edgex http://localhost:8765/mcp
```

### Claude Desktop (stdio through Docker)

Claude Desktop starts local servers as a process, so let it run the image in
stdio mode. The stack must already be up, because the container joins its
network. Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "qprime-edgex": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm", "--no-healthcheck",
        "--network", "qprime_qprime",
        "-e", "MCP_TRANSPORT=stdio",
        "-e", "EDGEX_METADATA_URL=http://edgex-core-metadata:59881",
        "-e", "EDGEX_DATA_URL=http://edgex-core-data:59880",
        "qprime-mcp:latest"
      ]
    }
  }
}
```

### Codex

The project's `.codex/config.toml` uses the HTTP endpoint. To add it by hand
instead:

```bash
codex mcp add qprime-edgex --url http://localhost:8765/mcp
```

If you set a token, add `bearer_token_env_var = "QPRIME_MCP_TOKEN"` under the
server's entry.

### Hermes Agent

Add this to `~/.hermes/profiles/<profile>/config.yaml`:

```yaml
mcp_servers:
  qprime-edgex:
    url: "http://localhost:8765/mcp"
    # headers:
    #   Authorization: "Bearer <token>"
```

### Ollama (local models)

Ollama is a model runtime, not an MCP client, so pair it with one such as
[ollmcp](https://github.com/jonigl/mcp-client-for-ollama). Use a model that
supports tool calling (for example, Qwen 3):

```bash
pip install ollmcp
ollmcp -u http://localhost:8765/mcp -m qwen3:8b -H http://localhost:11434
```

Hermes can also use an Ollama model directly: in `hermes model`, pick a custom
OpenAI-compatible endpoint at `http://localhost:11434/v1`.

## Run without Docker

```bash
pip install -r services/mcp/requirements.txt
python services/mcp/edgex_mcp.py                                 # stdio
MCP_TRANSPORT=streamable-http python services/mcp/edgex_mcp.py   # http://127.0.0.1:8765/mcp
```

Keep `mcp<2`. Version 2.x of the MCP SDK renamed `FastMCP`, so this file will
not import under it.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `EDGEX_METADATA_URL` | `http://localhost:59881` | EdgeX core-metadata |
| `EDGEX_DATA_URL` | `http://localhost:59880` | EdgeX core-data |
| `EDGEX_TOKEN` | – | Bearer token for EdgeX in secure mode |
| `EDGEX_STALE_SECONDS` | `60` | How old the last reading can be before a device counts as inactive |
| `MCP_TRANSPORT` | `stdio` (`streamable-http` in the image) | Transport |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` (`0.0.0.0` in the image) | HTTP bind address |
| `MCP_AUTH_TOKEN` | – | Require `Authorization: Bearer <token>` for HTTP clients |

## WSL note

If the client runs inside WSL, `localhost:8765` reaches the container as long
as Docker Desktop's WSL integration is on for that distro (Settings →
Resources → WSL integration).
