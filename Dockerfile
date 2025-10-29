FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies + uv globally
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates \
 && curl -LsSf https://astral.sh/uv/install.sh | sh \
 && mv /root/.local/bin/uv /usr/local/bin/uv \
 && mv /root/.local/bin/uvx /usr/local/bin/uvx \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /action

# Copy deps early for better layer caching
COPY requirements.txt /action/requirements.txt

# ✅ Use uv directly from /usr/local/bin
RUN uv pip install --system --no-cache -r /action/requirements.txt

# App code
COPY entrypoint.py /action/entrypoint.py

ENTRYPOINT ["python", "/action/entrypoint.py"]
