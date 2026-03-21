"""
Background job runner: wraps the existing motorshed Python algorithm
and converts results to GeoJSON for the frontend.
"""

import sys
import os
import traceback

# Ensure the motorshed package is importable from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# motorshed/osrm.py calls requests_cache.install_cache(backend='sqlite') at module
# import time. sqlite3 may not be available in all Python environments, so we patch
# install_cache to redirect to the memory backend before any motorshed imports happen.
import requests_cache as _rc
_orig_install_cache = _rc.install_cache
def _install_cache_memory(*args, **kwargs):
    kwargs['backend'] = 'memory'
    return _orig_install_cache(*args, **kwargs)
_rc.install_cache = _install_cache_memory


def run_job(job_id: str, lat: float, lng: float, radius_km: float,
            direction: str, jobs: dict):
    """
    Run the motorshed algorithm for a given origin (lat, lng) and
    update the shared `jobs` dict with progress and results.
    """
    def update(progress: int, message: str, status: str = "running"):
        jobs[job_id]["progress"] = progress
        jobs[job_id]["message"] = message
        jobs[job_id]["status"] = status

    try:
        import osmnx as ox
        from motorshed import osrm
        from motorshed.algos import gen2

        radius_m = int(radius_km * 1000)
        towards_origin = (direction != "from")

        # --- Stage 1: Fetch road network from OSM ---
        update(5, "Fetching road network from OpenStreetMap…")
        G = ox.graph_from_point(
            (lat, lng),
            dist=radius_m,
            network_type="drive",
            simplify=False,
        )
        G = ox.project_graph(G)

        # Initialize required graph attributes (mirrors overpass.get_map)
        for u, v, k, data in G.edges(data=True, keys=True):
            data["through_traffic"] = 1
        for node, data in G.nodes(data=True):
            data["calculated"] = False

        # Find the node closest to the clicked origin point.
        # ox.nearest_nodes(G, X, Y) takes longitude first, then latitude.
        center_node = ox.nearest_nodes(G, lng, lat)

        # --- Stage 2: OSRM Table API (batch transit times) ---
        update(15, "Querying OSRM for transit times…")
        osrm.get_transit_times(G, center_node, towards_origin=towards_origin)

        # --- Stage 3: Build routing dataframes ---
        update(30, "Building routing dataframes…")
        Gn, Ge = gen2.create_initial_dataframes(G, towards_origin=towards_origin)

        # --- Stage 4: Initial heuristic routing ---
        update(40, "Running initial heuristic routing…")
        Ge2, Gn2 = gen2.initial_routing(Ge.copy(), Gn.copy())

        # --- Stage 5: Follow-up heuristic routing ---
        update(52, "Running follow-up heuristic routing…")
        Ge3, Gn3 = gen2.followup_heuristic_routing(Ge2.copy(), Gn2.copy())

        # --- Stage 6: OSRM routing API for remaining ambiguous edges ---
        update(65, "Resolving remaining edges via OSRM routing API…")
        Ge4 = gen2.followup_osrm_routing_parallel(
            G, Ge3, Gn3, center_node, towards_origin=towards_origin
        )

        # --- Stage 7: Propagate traffic ---
        update(80, "Propagating traffic through network…")
        Gge = gen2.propagate_edges(Ge4)

        # --- Stage 8: Build GeoJSON ---
        update(93, "Building GeoJSON output…")
        geojson = edges_to_geojson(Gge, Gn, direction)

        jobs[job_id]["result"] = geojson
        update(100, "Done!", status="done")

    except Exception as exc:
        jobs[job_id]["error"] = str(exc)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = f"Error: {exc}"
        traceback.print_exc()


def edges_to_geojson(Gge, Gn, direction: str) -> dict:
    """
    Convert the propagated edge GeoDataFrame to a GeoJSON FeatureCollection.
    Each feature is a road segment with normalized traffic in [0, 1].
    """
    import math

    # Normalise traffic values for color mapping
    max_traffic = float(Gge.through_traffic.max() or 1)

    features = []
    for _, row in Gge.iterrows():
        # Skip ignored edges (footways, service roads) and zero-traffic edges
        if row.get("ignore", False):
            continue
        traffic = float(row.through_traffic)
        if traffic <= 0:
            continue

        # Look up WGS84 coordinates for start and end nodes
        try:
            u_node = Gn.loc[int(row.u)]
            v_node = Gn.loc[int(row.v)]
        except KeyError:
            continue

        coords = [
            [float(u_node.lon), float(u_node.lat)],
            [float(v_node.lon), float(v_node.lat)],
        ]

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "traffic": traffic / max_traffic,       # normalised 0-1
                "through_traffic": traffic,              # raw count
                "highway": str(row.highway),
                "direction": direction,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
