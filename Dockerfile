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

EXPOSE 8000 8501

# NOTE: the project now runs as two processes - the FastAPI service (api.py)
# that owns the crew, and the Streamlit app (app.py) that calls it over HTTP.
# This CMD starts only the front end, which on its own will show "could not
# reach the API". Running both properly needs either a process manager in the
# image or two images and a compose file; that has not been done or verified
# here, and saying so is better than shipping a CMD that looks right and is not.
#
# To run the API from this image instead:
#   docker run --env-file .env -p 8000:8000 crew \
#     uvicorn api:app --host 0.0.0.0 --port 8000
#
# Keys are passed in at run time (docker run --env-file .env ...), never baked in.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
