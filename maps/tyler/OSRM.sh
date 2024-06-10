#!/bin/bash

docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/tyler.osm.pbf
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/tyler.osrm
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/tyler.osrm
docker run -t -i -p 5000:5000 -v $(pwd):/data osrm/osrm-backend osrm-routed --algorithm mld /data/tyler.osrm
