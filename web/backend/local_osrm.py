"""
On-demand local OSRM server management.

Instead of pre-processing an entire state/region, this module:
1. Downloads raw OSM data from Overpass for the bounding box
2. Runs the OSRM pipeline (extract/partition/customize) via Docker
3. Starts a temporary OSRM server on a dynamic port
4. Provides the server URL for routing
5. Cleans up when done

We download raw OSM data (rather than re-exporting the OSMnx graph)
because OSRM needs the original OSM ways/relations to route correctly.
"""

import hashlib
import os
import shutil
import socket
import subprocess
import tempfile
import time

import requests as req

# Directory for caching downloaded OSM files
_OSM_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "motorshed", "cache", "osm_downloads")

# When running inside Docker, temp files must be on a path shared with the host
# so sibling OSRM containers can mount them. Set OSRM_TMPDIR to a shared path.
OSRM_TMPDIR = os.environ.get("OSRM_TMPDIR", tempfile.gettempdir())

# When running inside a Docker container, "localhost" refers to the container
# itself, not the host. Use DOCKER_HOST_ADDR to reach ports on the host.
DOCKER_HOST_ADDR = os.environ.get("DOCKER_HOST_ADDR", "localhost")


def _find_free_port():
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(url, timeout=60):
    """Wait for the OSRM server to become responsive."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = req.get(f"{url}/nearest/v1/driving/0,0", timeout=2)
            return True
        except (req.ConnectionError, req.Timeout):
            time.sleep(0.5)
    return False


# Highway types to download per mode.
# Driving: standard road network
# Cycling: roads + bike infrastructure
# Walking: roads + all pedestrian infrastructure
HIGHWAY_TYPES = {
    "car.lua": "motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|service|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link",
    "bicycle.lua": "motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|service|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|cycleway|path|track|pedestrian",
    "foot.lua": None,  # Download ALL highways — foot.lua decides what's routable
}


def _download_osm_bbox(south, west, north, east, filepath, lua_profile="car.lua", on_status=None):
    """Download raw OSM data for a bounding box from Overpass API. Uses file cache."""
    on_status = on_status or (lambda msg: None)
    # Add a small buffer to ensure we get roads at the edges
    buf = 0.005
    highway_filter = HIGHWAY_TYPES.get(lua_profile, HIGHWAY_TYPES["car.lua"])
    if highway_filter is None:
        # Download all highways — let OSRM's profile decide what's routable
        way_filter = f'way["highway"]({south - buf},{west - buf},{north + buf},{east + buf});'
    else:
        way_filter = f'way["highway"~"{highway_filter}"]({south - buf},{west - buf},{north + buf},{east + buf});'
    query = f"""
    [out:xml][timeout:120];
    (
      {way_filter}
    );
    (._;>;);
    out body;
    """

    # Check file cache
    cache_key = hashlib.sha256(query.encode()).hexdigest()[:16]
    os.makedirs(_OSM_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(_OSM_CACHE_DIR, f"{cache_key}.osm")
    if os.path.exists(cache_path):
        on_status("Using cached road data")
        shutil.copy2(cache_path, filepath)
        return

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            r = req.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
                headers={"User-Agent": "Travelshed/1.0"},
                timeout=120,
            )
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            # Save to cache
            shutil.copy2(filepath, cache_path)
            return
        except (req.ConnectionError, req.Timeout, req.HTTPError) as exc:
            if attempt == max_retries:
                raise
            delay = 2 ** attempt  # 2s, 4s
            on_status(f"Overpass request failed, retrying in {delay}s (attempt {attempt}/{max_retries})…")
            time.sleep(delay)


def _download_osm_place(place, filepath, lua_profile="car.lua", on_status=None):
    """Download raw OSM data for a named place.
    Uses Nominatim to get the bounding box, then downloads via Overpass bbox query.
    This is much faster than Overpass area queries.
    """
    on_status = on_status or (lambda msg: None)
    # Geocode the place to get its bounding box (with retries)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            r = req.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": place, "format": "json", "limit": 1},
                headers={"User-Agent": "Travelshed/1.0"},
                timeout=30,
            )
            r.raise_for_status()
            results = r.json()
            break
        except (req.ConnectionError, req.Timeout, req.HTTPError) as exc:
            if attempt == max_retries:
                raise
            delay = 2 ** attempt
            on_status(f"Nominatim request failed, retrying in {delay}s (attempt {attempt}/{max_retries})…")
            time.sleep(delay)

    if not results:
        raise ValueError(f"Place not found: {place}")

    bbox = results[0]["boundingbox"]  # [south, north, west, east]
    south, north = float(bbox[0]), float(bbox[1])
    west, east = float(bbox[2]), float(bbox[3])

    _download_osm_bbox(south, west, north, east, filepath, lua_profile=lua_profile, on_status=on_status)


class LocalOSRM:
    """
    Manages a temporary, on-demand OSRM server for a specific area.

    Usage:
        with LocalOSRM(lat, lng, radius_km=3) as osrm:
            # osrm.host is e.g. "http://localhost:54321"
            response = requests.get(f"{osrm.host}/route/v1/driving/...")

    Or for a named place:
        with LocalOSRM(lat, lng, place="San Francisco, CA") as osrm:
            ...
    """

    def __init__(self, lat, lng, radius_km=3, place=None, lua_profile="car.lua",
                 osm_file=None, on_status=None):
        self.lat = lat
        self.lng = lng
        self.radius_km = radius_km
        self.place = place
        self.lua_profile = lua_profile
        self.osm_file = osm_file  # Pre-downloaded OSM file to use
        self.on_status = on_status or (lambda msg: None)
        self.host = None
        self._port = None
        self._tmpdir = None
        self._container_name = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def start(self):
        """Download raw OSM data, run OSRM pipeline, start server."""
        os.makedirs(OSRM_TMPDIR, exist_ok=True)
        self._tmpdir = tempfile.mkdtemp(prefix="osrm_", dir=OSRM_TMPDIR)
        osm_path = os.path.join(self._tmpdir, "graph.osm")

        # Step 1: Get raw OSM data (use pre-downloaded file or download fresh)
        if self.osm_file:
            import shutil
            shutil.copy2(self.osm_file, osm_path)
        elif self.place:
            self.on_status(f"Downloading road data for {self.place}…")
            _download_osm_place(self.place, osm_path, lua_profile=self.lua_profile, on_status=self.on_status)
        else:
            self.on_status("Downloading road data from OpenStreetMap…")
            # Convert radius to approximate bounding box
            # 1 degree latitude ≈ 111km
            dlat = self.radius_km / 111.0
            dlng = self.radius_km / (111.0 * abs(
                __import__('math').cos(__import__('math').radians(self.lat))
            ))
            _download_osm_bbox(
                self.lat - dlat, self.lng - dlng,
                self.lat + dlat, self.lng + dlng,
                osm_path,
                lua_profile=self.lua_profile,
                on_status=self.on_status,
            )

        file_size = os.path.getsize(osm_path)
        self.on_status(
            f"Downloaded {file_size / 1024 / 1024:.1f} MB of road data"
        )

        # Step 2: Run OSRM extract
        self.on_status("Processing road network (extract)…")
        self._docker_run(
            "osrm-extract", "-p", f"/opt/{self.lua_profile}", "/data/graph.osm"
        )

        # Step 3: Run OSRM partition
        self.on_status("Processing road network (partition)…")
        self._docker_run("osrm-partition", "/data/graph.osrm")

        # Step 4: Run OSRM customize
        self.on_status("Processing road network (customize)…")
        self._docker_run("osrm-customize", "/data/graph.osrm")

        # Step 5: Start OSRM server
        self._port = _find_free_port()
        self._container_name = f"osrm-ondemand-{self._port}"
        self.host = f"http://{DOCKER_HOST_ADDR}:{self._port}"

        self.on_status("Starting local routing server…")
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", self._container_name,
                "-p", f"{self._port}:5000",
                "-v", f"{self._tmpdir}:/data",
                "osrm/osrm-backend",
                "osrm-routed", "--algorithm", "mld", "/data/graph.osrm",
            ],
            check=True,
            capture_output=True,
        )

        if not _wait_for_server(self.host):
            raise RuntimeError("OSRM server failed to start")

        self.on_status("Local routing server ready")

    def stop(self):
        """Stop the OSRM container and clean up temp files."""
        if self._container_name:
            subprocess.run(
                ["docker", "rm", "-f", self._container_name],
                capture_output=True,
            )
            self._container_name = None

        if self._tmpdir and os.path.exists(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

        self.host = None

    def _docker_run(self, *args):
        """Run an OSRM Docker command on the temp data directory."""
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{self._tmpdir}:/data",
                "osrm/osrm-backend",
                *args,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"OSRM command failed: {' '.join(args)}\n{result.stderr}"
            )
