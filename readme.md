# Install dependencies (OSMNX and other stuff)

```sh
conda config --add channels conda-forge 
conda create -c conda-forge --override-channels --name geo osmnx tqdm selenium phantomjs pillow bokeh jupyter requests_cache
pip install contexttimer
source activate geo
```

Note that `selenium phantomjs pillow` are [necessary](https://bokeh.pydata.org/en/latest/docs/user_guide/export.html) to export `bokeh` plots. 

## Example:

```sh
python
import motorshed
from bokeh.io import export_png
address = 'Astoria, OR'
G, center_node, origin_point = motorshed.get_map(address, distance=20000)
```

### or, you can run by place:
```python
place = 'Clatsop County, Oregon, USA'
G, center_node, origin_point = motorshed.get_map(address, place=place)
```

### then analyze and draw the map (5-200 it/s seems normal):
```python
motorshed.get_transit_times(G, origin_point)
missing_edges, missing_nodes = motorshed.find_all_routes(G, center_node)
motorshed.make_bokeh_map(G, center_node, color_by='through_traffic')
export_png(p, filename='Astoria OR.png')
```

![alt text](images/Clatsop.png "Clatsop County")

### To make animations, set `show_progress=True` and use convert from the command line:
```
convert -delay 10 -loop 0 *.png animate-Clatsop-by-time.gif
```

## You may also want to run [OSRM](http://project-osrm.org) to do your own routing. 

Although we recommend starting with the remote server by setting local_host=False (which is default), it is possible to do routing on your local machine. You will need to install `osmconvert` (on a Mac: `brew install osmfilter`or [from source](https://wiki.openstreetmap.org/wiki/Osmconvert#Source)), and the OSRM [docker](https://hub.docker.com/r/osrm/osrm-backend/). Each time you download a map from OpenStreetMap you will need to save it to disk with `ox.save_graph_xml(G)`. Then you can convert the OSM XML map to .pbf, compile, and run the routing machine with a script like OSRM.sh, which has the following commands:
```bash
cd data
osmconvert graph.osm -o=graph.osm.pbf

docker run -t -v $(pwd):/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/graph.osm.pbf
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-partition /data/graph.osrm
docker run -t -v $(pwd):/data osrm/osrm-backend osrm-customize /data/graph.osrm
docker run -t -i -p 5000:5000 -v $(pwd):/data osrm/osrm-backend osrm-routed --algorithm mld /data/graph.osrm
```

You'll have to run `chmod u+x OSRM.sh` to make the script executable.
If you get an error about "Port 5000 already in use" then you might have to shut down Airplay Receiver: https://medium.com/pythonistas/port-5000-already-in-use-macos-monterey-issue-d86b02edd36c