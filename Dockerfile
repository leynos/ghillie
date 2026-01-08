# Ghillie container image
# Multi-stage build for minimal runtime image size
#
# Build:
#   docker build -t ghillie:local .
#
# Run:
#   docker run --rm -p 8080:8080 ghillie:local

# =============================================================================
# Build stage: Create wheel from source
# =============================================================================
FROM python:3.12-slim AS build

WORKDIR /build

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Copy package definition first (for better layer caching)
COPY pyproject.toml README.md /build/

# Copy source code
COPY ghillie /build/ghillie

# Build wheel
RUN pip wheel --no-deps --wheel-dir /wheels .

# =============================================================================
# Runtime stage: Minimal image with installed package
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash --uid 1000 ghillie

# Copy wheel from build stage and install
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy entrypoint script with execute permissions
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/ghillie-entrypoint

# Switch to non-root user
USER ghillie

# Expose the default HTTP port
EXPOSE 8080

# Set environment defaults
ENV GHILLIE_HOST=0.0.0.0 \
    GHILLIE_PORT=8080 \
    GHILLIE_LOG_LEVEL=INFO

# Use entrypoint for signal handling
ENTRYPOINT ["ghillie-entrypoint"]

# Default command: run the Ghillie runtime
CMD ["python", "-m", "ghillie.runtime"]
