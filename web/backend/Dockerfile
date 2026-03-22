FROM python:3.11-slim

WORKDIR /app

# Install system deps for geopandas/osmnx + Docker CLI for on-demand OSRM
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgdal-dev libspatialindex-dev \
    curl ca-certificates \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY web/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy motorshed library and install it
COPY motorshed/ /app/motorshed/
COPY setup.py /app/
RUN pip install --no-cache-dir -e .

# Copy backend code
COPY web/backend/ /app/backend/

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
