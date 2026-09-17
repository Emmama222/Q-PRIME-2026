FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY edgex_mcp.py /app/edgex_mcp.py

# Run as an unprivileged user.
RUN useradd --system --uid 10001 mcp
USER mcp

# Container default: long-running HTTP server. For stdio clients (Claude Desktop),
# override with `-e MCP_TRANSPORT=stdio` and run with `docker run -i`.
ENV PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"

CMD ["python", "edgex_mcp.py"]
