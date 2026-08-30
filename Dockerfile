FROM python:3.11-slim

# uv comes from its official image. Pinned rather than :latest so a rebuild
# months from now installs the same way this one did - and pinned to the same
# version used locally, which is the point of using uv in both places.
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

# Charts, PDFs and the disk cache are written here at runtime. Both are
# declared as volumes in docker-compose.yml so they survive a restart.
RUN mkdir -p output .cache

# 8000 is the API, 8501 is the Streamlit app. One container will use one of
# them; both are declared because this image can be either.
EXPOSE 8000 8501

# The API is the default: it is the half that actually does the work, and the
# app is useless without it. docker-compose.yml overrides this for the front
# end. Run either directly with:
#
#   docker run --env-file .env -p 8000:8000 crew
#   docker run --env-file .env -p 8501:8501 -e API_URL=http://host.docker.internal:8000 \
#     crew streamlit run app.py --server.address=0.0.0.0 --server.headless=true
#
# Keys are passed in at run time (--env-file .env), never baked into the image.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
