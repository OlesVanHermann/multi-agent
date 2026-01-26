FROM python:3.11-slim

WORKDIR /app

# Install SSH client
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
RUN pip install --no-cache-dir redis

# Create state directory
RUN mkdir -p /app/state

COPY bridge.py /app/

CMD ["python", "bridge.py"]
