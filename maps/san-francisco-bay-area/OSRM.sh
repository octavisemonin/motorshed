#!/bin/bash

docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/san-francisco-bay-area.osm.pbf
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/san-francisco-bay-area.osrm
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/san-francisco-bay-area.osrm
docker run -t -i -p 5000:5000 -v $(pwd):/data osrm/osrm-backend osrm-routed --algorithm mld /data/san-francisco-bay-area.osrm
