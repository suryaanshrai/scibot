FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /bin/

WORKDIR /app

ARG TORCH_VERSION=2.10.0
ARG TORCHVISION_VERSION=0.25.0

ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./

# The lockfile resolves Linux torch with its CUDA runtime: several GB of
# nvidia-*, triton and cuda-* wheels. `uv sync --no-install-package` still
# downloads those, so install from the exported pins instead: drop torch and
# the GPU-only wheels, install everything else exactly as locked (--no-deps,
# since the export is the complete pinned set), then add CPU-only torch.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-hashes --no-emit-project --no-annotate --no-header \
        -o /tmp/requirements.txt \
    && grep -vE '^(torch|torchvision|triton|cuda-[a-z-]+|nvidia-[a-z0-9-]+)==' \
        /tmp/requirements.txt > /tmp/requirements-cpu.txt \
    && uv venv /app/.venv --python /usr/local/bin/python3 \
    && uv pip install --python /app/.venv/bin/python --no-deps -r /tmp/requirements-cpu.txt \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==${TORCH_VERSION} torchvision==${TORCHVISION_VERSION}

COPY . .


FROM node:22-alpine AS frontend-builder

WORKDIR /app/app/frontend

COPY app/frontend/package.json app/frontend/package-lock.json ./

RUN npm ci --legacy-peer-deps

COPY app/frontend ./

RUN npm run build


FROM python:3.12-slim

LABEL org.opencontainers.image.title="SciBot" \
      org.opencontainers.image.description="Multi-agent, multi-modal RAG assistant for research" \
      org.opencontainers.image.source="https://github.com/suryaanshrai/scibot" \
      org.opencontainers.image.licenses="GPL-3.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /app /app
COPY --from=frontend-builder /app/app/frontend/dist /app/app/frontend/dist

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]