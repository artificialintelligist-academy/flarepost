# Build stage: uv installs Flarepost and its locked dependencies into /app/.venv.
FROM python:3.13-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

# Compile bytecode for a faster start, copy instead of linking from the cache,
# and use the image's Python instead of downloading one.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Dependencies first, in their own layer, so changing our code does not reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --no-editable

# Then Flarepost itself, installed as a package so the image needs no source code.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# Final stage: only Python and the virtual environment, run by a user without root.
FROM python:3.13-slim-trixie
RUN useradd --create-home flarepost
# The database lives in /data, where a volume keeps it when the container goes away.
RUN mkdir /data && chown flarepost /data
ENV FLAREPOST_DB=/data/flarepost.db
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER flarepost
EXPOSE 8000
CMD ["flarepost", "--http", "--host", "0.0.0.0"]