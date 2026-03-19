# NeuralClaw — Production Dockerfile
# Multi-stage build: keeps final image lean

# ── Build stage ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY neuralclaw/ neuralclaw/

RUN pip install --no-cache-dir build && python -m build --wheel
RUN pip install --no-cache-dir dist/*.whl "neuralclaw[vector]"

# ── Runtime stage ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install Playwright system deps + curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libexpat1 libxcb1 libxkbcommon0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
    libxrandr2 libgbm1 libdrm2 libpango-1.0-0 libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/neuralclaw /usr/local/bin/neuralclaw

# Create non-root user
RUN useradd -m -u 1000 neuralclaw
USER neuralclaw
WORKDIR /home/neuralclaw

# Data volume — config, memory DB, logs
VOLUME ["/home/neuralclaw/.neuralclaw"]

# Install Playwright browsers (run once, baked into image for session providers)
RUN python -m playwright install chromium

EXPOSE 8080 8100 9090

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["neuralclaw"]
CMD ["gateway"]
