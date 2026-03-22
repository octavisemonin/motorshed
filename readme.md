# Motorshed

Motorshed is an open-source project to explore and visualize traffic patterns using beautiful, stylized maps.

A **Motorshed Map** shows the flow of traffic to (or from) a single point on the map (origin point),
from (or to) every other point on the map. A motorshed (our term) is named by analogy to a watershed map,
which shows the flow of water downhill from every point in a watershed to a single outlet point. But
whereas water follows the elevation gradient, traffic follows the travel-time-to-destination gradient.

Motorshed maps are meant to be interesting, thought-provoking, and aesthetically pleasing. But,
they are also (ostensibly) useful: given a motorshed map with your home as the origin point, you
can trace the lines (biggest to smallest) to find the quickest route from your house to any point
on the map, and vice-versa.

You might also find the maps useful for carpool planning (with the origin as your workplace?).

The basic motorshed map can be extended in a few interesting ways:

* **The bidirectional map**: shows the *from* and *to* maps either side-by-side, or overlaid with
  different colors. The maps differ slightly due to, e.g., one-way-streets and difficult left turns.
* **The Bicycle, Pedestrian, or Public Transit Map**: is like a motorshed, but for alternate
  modes of transportation. It can be fun/interesting to compare motorsheds with bikesheds, sneakersheds,
  or... transitsheds? (Obviously, we could use some help on the naming :) )
* **The Transit-time Map**: You can add transit-time information to the map by, e.g. coloring the lines
  or adding isochrone (equal-travel-time) contours. You can even plot a 3-d map where elevation is given
  by the contours. The use-cases are obvious, but we've found it's hard to get this much info on a
  motorshed map without destroying the aesthetics. We'd love to see some cool suggestions!

An example tri-pane bidirectional map of a street address in San Francisco (10km on a side):

![Bidirectional map](images/example_10k_sf_bidir_tripane.png)

Or, for the New York Stock Exchange (see the notebooks for this example):
![Bidirectional map](images/11%20Wall%20Street%20New%20York%20NY.5000.bi_dir_tri_pane.png)

## Web App (recommended)

The easiest way to use Motorshed is the interactive web app, which lets you click anywhere on a map,
choose a radius and direction, and watch the motorshed render in real time.

### Prerequisites

- **Docker** (for the local OSRM routing server)
- **Node.js** (for the frontend)
- **Python 3.9+** (for the backend)

### 1. Set up a local OSRM server

A local OSRM server is **strongly recommended** — it's dramatically faster than the public server
and avoids rate limits. The setup script downloads an OSM extract, processes it for OSRM, and
starts a Docker container:

```sh
cd web

# First time: downloads and processes the map data (takes a while)
./osrm-setup.sh

# Subsequent runs: just start the server
./osrm-setup.sh start
```

The OSRM server will be available at `http://localhost:5001`. By default the script
uses the California extract; edit the script to change the region.

### 2. Start the backend

```sh
cd web/backend
pip install -r requirements.txt
OSRM_HOST=http://localhost:5001 uvicorn main:app --reload --port 8000
```

### 3. Start the frontend

```sh
cd web/frontend
npm install
npm run dev
```

Then open `http://localhost:5173` in your browser. Click a point on the map, adjust the radius,
and hit **Compute Motorshed**.

## How it works

Motorshed uses a **brute-force routing** approach: for every node in the road network within
the chosen radius, it queries OSRM for the shortest route to (or from) the origin point, then
accumulates traffic counts on each edge. The result is a heat map showing which roads carry
the most aggregate traffic.

> **Note**: The codebase also contains an experimental heuristic propagation approach (`gen2.py`)
> that attempts to avoid the per-node OSRM calls. This does not currently produce good results
> and should not be used.

## Scripts and Notebooks

We've created a couple of scripts that demonstrate how to make a basic (very small) map.

In the base repo directory, run

```
python motorshed/scripts/run_basic_map.py
```

which should create a small test map (4km on a side) leading to the Foster City, CA Tesla
dealership. (Note the cool road pattern of the engineered landfill neighborhood.)

![Basic map](images/391%20Foster%20City%20Blvd%20Foster%20City%20CA%2094404.3000.basic_example.png)

Or, to make a bidirectional map (shows traffic in both directions), run:

```
python motorshed/scripts/run_bidir_map.py
```

The tri-pane version of this map (showing to, from, and combined views) looks like:
![Bidirectional map](images/391%20Foster%20City%20Blvd%20Foster%20City%20CA%2094404.3000.bi_dir_tri_pane.png)

### Notebooks

Just run `jupyter notebook` in, e.g., the `notebooks` directory. This is a great
way to explore the maps, and there are several examples to get you started.

You can browse most of the notebooks on Github to see what they look like.
* [**Basic Example**](notebooks/basic%20example%20notebook.ipynb) ("notebooks/basic example notebook.ipynb"): A smaller, uni-directional map that runs pretty quickly.
* [**Bidirectional Example**](notebooks/bidirectional%20example.ipynb) ("notebooks/bidirectional example.ipynb"): A bigger tri-pane map that shows traffic in both directions, in different colors, and which runs a lot more slowly.

## Python library setup

If you want to use the motorshed Python library directly (for scripts or notebooks):

```sh
# Creates conda environment named 'motorshed'
conda env create -f environment.yaml
conda activate motorshed

# Install the package in editable mode
pip install -e ./
```

To confirm that it worked, try running `import motorshed` in any Python terminal.

### To run the tests

```sh
pytest ./
```

## Important notes

The public OSRM and Overpass services are free — please don't abuse them. For anything beyond
a quick test, use a local OSRM server (see above) or a paid API like Mapbox.
