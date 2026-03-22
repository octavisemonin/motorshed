#!/bin/bash
# Set up a local OSRM server for California using Docker.
#
# Usage:
#   ./osrm-setup.sh          # Download, process, and start
#   ./osrm-setup.sh start    # Just start (if already processed)
#
# The server runs on http://localhost:5001

set -e

REGION="california"
DATA_DIR="$(cd "$(dirname "$0")" && pwd)/osrm-data"
PBF_URL="https://download.geofabrik.de/north-america/us/${REGION}-latest.osm.pbf"
PBF_FILE="${DATA_DIR}/${REGION}-latest.osm.pbf"
OSRM_FILE="${DATA_DIR}/${REGION}-latest.osrm"

mkdir -p "$DATA_DIR"

if [ "$1" = "start" ]; then
    echo "Starting OSRM server on http://localhost:5001 ..."
    docker run -t -i -p 5001:5000 -v "$DATA_DIR:/data" \
        osrm/osrm-backend osrm-routed --algorithm mld "/data/${REGION}-latest.osrm"
    exit 0
fi

# Step 1: Download the PBF extract
if [ ! -f "$PBF_FILE" ]; then
    echo "Downloading ${REGION} OSM extract (~1.2 GB)..."
    curl -L -o "$PBF_FILE" "$PBF_URL"
else
    echo "PBF file already exists, skipping download."
fi

# Step 2: Extract (build the routing graph)
echo "Extracting routing graph (this takes a few minutes)..."
docker run -t -v "$DATA_DIR:/data" \
    osrm/osrm-backend osrm-extract -p /opt/car.lua "/data/${REGION}-latest.osm.pbf"

# Step 3: Partition
echo "Partitioning..."
docker run -t -v "$DATA_DIR:/data" \
    osrm/osrm-backend osrm-partition "/data/${REGION}-latest.osrm"

# Step 4: Customize
echo "Customizing..."
docker run -t -v "$DATA_DIR:/data" \
    osrm/osrm-backend osrm-customize "/data/${REGION}-latest.osrm"

# Step 5: Start the server
echo "Starting OSRM server on http://localhost:5001 ..."
docker run -t -i -p 5001:5000 -v "$DATA_DIR:/data" \
    osrm/osrm-backend osrm-routed --algorithm mld "/data/${REGION}-latest.osrm"
