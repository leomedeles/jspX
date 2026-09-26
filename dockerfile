# syntax=docker/dockerfile:1
FROM python:3.12-slim

# System deps (keep tiny; libgomp1 helps with numpy/numba stacks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd -ms /bin/bash appuser
WORKDIR /app

# Install Python deps
# Keep the image installation identical to the documented host installation.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY src ./src

# Defaults (overridden by .env / compose)
ENV BROKER_URL=mqtt://mosquitto:1883 \
    PUB_TOPIC=telemetry/pandapower \
    RATE_HZ=1

USER appuser

# Simple healthcheck: can we reach the broker?
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,socket;url=os.getenv('BROKER_URL','mqtt://mosquitto:1883').split('://')[-1];h,p=url.split(':');s=socket.socket();s.settimeout(2);s.connect((h,int(p)));s.close()"

# Start the sim the same way you do locally
CMD ["python", "src/power_sim.py", "--mqtt", "--pandapower"]
