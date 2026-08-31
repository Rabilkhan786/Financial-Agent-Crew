FROM python:3.11-slim

# Pinned uv version so a rebuild later installs the same way this one did.
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app

# Installed before the app code, so this layer stays cached between builds.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# Charts, PDFs and the disk cache are written here. docker-compose.yml
# mounts both as volumes so they survive a restart.
RUN mkdir -p output .cache

# 8000 = API, 8501 = Streamlit app. Each container uses one of them.
EXPOSE 8000 8501

# Default: run as the API. docker-compose.yml overrides this for the app
# container - use `docker compose up --build` to run both normally.
#
# To run one container by hand instead:
#
#   docker build -t crew .
#   docker run --env-file .env -p 8000:8000 crew
#
#   docker run --env-file .env -p 8501:8501 \
#     -e API_URL=http://host.docker.internal:8000 \
#     -e API_PUBLIC_URL=http://localhost:8000 \
#     crew streamlit run app.py --server.address=0.0.0.0 --server.headless=true
#
# Two different API addresses because they're used by two different callers:
# API_URL is used by this container to reach the API container. API_PUBLIC_URL
# is used by the reader's browser, which can't resolve host.docker.internal.
# See config.py's comment on API_PUBLIC_URL.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
