FROM python:3.13-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
WORKDIR /app
RUN uv sync --frozen --no-cache

ENV PYTHONPATH="/app/src:/app:${PYTHONPATH}"
ENV TZ=Asia/Seoul

# Playwright 브라우저 설치 (이거 추가!)
RUN /app/.venv/bin/playwright install --with-deps

# Run the application.
CMD ["/app/.venv/bin/fastapi", "run", "main.py", "--port", "8000", "--host", "0.0.0.0"]
