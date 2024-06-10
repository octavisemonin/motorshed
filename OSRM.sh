#!/bin/bash

cd data
osmconvert graph.osm -o=graph.osm.pbf

docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/graph.osm.pbf
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/graph.osrm
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/graph.osrm
docker run -t -i -p 5000:5000 -v $(pwd):/data osrm/osrm-backend osrm-routed --algorithm mld /data/graph.osrm
