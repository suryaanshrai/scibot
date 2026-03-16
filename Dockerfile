FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/

WORKDIR /app

ARG TORCH_VERSION=2.10.0
ARG TORCHVISION_VERSION=0.25.0

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen \
    --no-install-package torch \
    --no-install-package torchvision

# The lockfile currently resolves Linux torch wheels with CUDA runtime
# dependencies. Skip those packages during uv sync, then install CPU-only
# wheels once so the image never downloads the GPU stack.
RUN uv pip install --python /app/.venv/bin/python --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==${TORCH_VERSION} torchvision==${TORCHVISION_VERSION}


FROM node:22-alpine AS frontend-builder

WORKDIR /app/app/frontend

COPY app/frontend/package.json app/frontend/package-lock.json ./

RUN npm ci --legacy-peer-deps

COPY app/frontend ./

RUN npm run build


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app /app
COPY --from=frontend-builder /app/app/frontend/dist /app/app/frontend/dist

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]