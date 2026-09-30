FROM python:3.12-slim AS builder

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml README.md ./
COPY src/ ./src/
# The wheel force-includes the SQL seeds as ignis/sql, so the build needs them present.
COPY sql/ ./sql/

RUN uv venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN uv pip install --no-cache -e .

FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY src/ ./src/
COPY sql/ ./sql/

ENV PYTHONUNBUFFERED=1

# GHCR links the package to its repository through the source label, and the MCP Registry binds
# the image to server.json only when the server-name label equals server.json's `name` exactly.
LABEL org.opencontainers.image.source="https://github.com/fioenix/fn-ignis"
LABEL io.modelcontextprotocol.server.name="io.github.fioenix/fn-ignis"

# The image is the OCI package server.json advertises, so its only default process is the
# request-driven MCP server. An idle installation starts no collection process.
CMD ["python", "-m", "ignis.interfaces.mcp.server"]
