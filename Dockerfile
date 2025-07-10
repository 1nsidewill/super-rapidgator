FROM python:3.13-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
WORKDIR /app
RUN uv sync --frozen --no-cache

ENV PYTHONPATH="/app/src:/app:${PYTHONPATH}"

# Run the application.
CMD ["uv", "icorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]