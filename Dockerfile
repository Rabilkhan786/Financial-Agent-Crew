# Streamlit app image. Dependencies are installed with uv (same tool used locally),
# reading the same requirements.txt, so the container matches the dev environment.
FROM python:3.11-slim

# uv comes from its official image — no pip bootstrap needed.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# Charts and PDFs are written here at runtime.
RUN mkdir -p output .cache

EXPOSE 8501

# Keys are passed in at run time (docker run --env-file .env ...), never baked in.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
