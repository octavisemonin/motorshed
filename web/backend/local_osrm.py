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

import os
import shutil
import socket
import subprocess
import tempfile
import time

import requests as req

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


def _download_osm_bbox(south, west, north, east, filepath):
    """Download raw OSM data for a bounding box from Overpass API."""
    # Add a small buffer to ensure we get roads at the edges
    buf = 0.005
    query = f"""
    [out:xml][timeout:120];
    (
      way["highway"~"motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|service|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"]
        ({south - buf},{west - buf},{north + buf},{east + buf});
    );
    (._;>;);
    out body;
    """
    r = req.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        timeout=120,
    )
    r.raise_for_status()
    with open(filepath, "wb") as f:
        f.write(r.content)


def _download_osm_place(place, filepath):
    """Download raw OSM data for a named place.
    Uses Nominatim to get the bounding box, then downloads via Overpass bbox query.
    This is much faster than Overpass area queries.
    """
    # Geocode the place to get its bounding box
    r = req.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "json", "limit": 1},
        headers={"User-Agent": "Motorshed/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Place not found: {place}")

    bbox = results[0]["boundingbox"]  # [south, north, west, east]
    south, north = float(bbox[0]), float(bbox[1])
    west, east = float(bbox[2]), float(bbox[3])

    _download_osm_bbox(south, west, north, east, filepath)


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

    def __init__(self, lat, lng, radius_km=3, place=None, on_status=None):
        self.lat = lat
        self.lng = lng
        self.radius_km = radius_km
        self.place = place
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

        # Step 1: Download raw OSM data
        if self.place:
            self.on_status(f"Downloading road data for {self.place}…")
            _download_osm_place(self.place, osm_path)
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
            )

        file_size = os.path.getsize(osm_path)
        self.on_status(
            f"Downloaded {file_size / 1024 / 1024:.1f} MB of road data"
        )

        # Step 2: Run OSRM extract
        self.on_status("Processing road network (extract)…")
        self._docker_run(
            "osrm-extract", "-p", "/opt/car.lua", "/data/graph.osm"
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
