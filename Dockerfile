# InvestPanel container — runs the Streamlit app.
# Uses uv (not pip) to install the exact locked dependencies, matching local dev.

FROM python:3.11-slim

# Install uv (the same tool used in development).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy just the dependency manifests first so Docker can cache the install layer.
COPY pyproject.toml uv.lock .python-version ./

# Install exactly what's in uv.lock — reproducible, no surprise upgrades.
RUN uv sync --frozen --no-dev

# Now copy the rest of the source.
COPY . .

# Streamlit's default port.
EXPOSE 8501

# API keys are provided at runtime via environment variables / a mounted .env,
# never baked into the image.
CMD ["uv", "run", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
