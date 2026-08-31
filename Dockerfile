FROM python:3.12-slim AS builder

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml README.md ./
COPY src/ ./src/

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

CMD ["python", "-m", "ignis.interfaces.cli.scheduler"]
