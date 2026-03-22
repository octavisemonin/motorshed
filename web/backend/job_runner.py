"""
Background job runner: wraps the existing motorshed Python algorithm
and converts results to GeoJSON for the frontend.

Uses the brute_force algorithm which queries OSRM for an actual route
from every node to the center, producing complete coverage with no gaps.

OSRM server selection:
  - If OSRM_HOST env var is set, uses that (pre-built server).
  - Otherwise, spins up a temporary on-demand OSRM server via Docker
    for just the requested area. This uses minimal RAM and works anywhere.
"""

import sys
import os
import traceback
import concurrent.futures

# Ensure the motorshed package is importable from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Check if a pre-built OSRM server is configured
OSRM_HOST = os.environ.get("OSRM_HOST", "")


def run_job(job_id: str, lat: float, lng: float, radius_km: float,
            direction: str, place: str | None, jobs: dict):
    """
    Run the motorshed algorithm for a given origin (lat, lng) and
    update the shared `jobs` dict with progress and results.

    If `place` is provided (e.g. "San Francisco, CA"), the road network
    is fetched by city boundary instead of radius.
    """
    def update(progress: int, message: str, status: str = "running"):
        jobs[job_id]["progress"] = progress
        jobs[job_id]["message"] = message
        jobs[job_id]["status"] = status

    try:
        import osmnx as ox

        towards_origin = (direction != "from")

        # --- Stage 1: Fetch road network from OSM ---
        if place:
            update(5, f"Fetching road network for {place}…")
            G = ox.graph_from_place(
                place,
                network_type="drive",
                simplify=False,
            )
        else:
            radius_m = int(radius_km * 1000)
            update(5, "Fetching road network from OpenStreetMap…")
            G = ox.graph_from_point(
                (lat, lng),
                dist=radius_m,
                network_type="drive",
                simplify=False,
            )

        # Find nearest node BEFORE projecting (x/y are lng/lat here)
        center_node = ox.nearest_nodes(G, lng, lat)

        # Add lat/lon attributes that the OSRM module expects,
        # using the unprojected x/y (which ARE lng/lat)
        for node, data in G.nodes(data=True):
            data["lon"] = data["x"]
            data["lat"] = data["y"]

        # Now project for the algorithm
        G = ox.project_graph(G)

        # Initialize required graph attributes
        for u, v, k, data in G.edges(data=True, keys=True):
            data["through_traffic"] = 1
        for node, data in G.nodes(data=True):
            data["calculated"] = False

        # --- Stage 2: Route every node via OSRM (brute force) ---
        if OSRM_HOST:
            # Use pre-built OSRM server
            _route_with_host(G, center_node, towards_origin, direction,
                             OSRM_HOST, job_id, jobs, update)
        else:
            # Spin up on-demand OSRM for just this area
            _route_on_demand(G, lat, lng, radius_km, place,
                             center_node, towards_origin,
                             direction, job_id, jobs, update)

        # --- Stage 3: Final GeoJSON ---
        update(90, "Finalizing…")
        geojson = graph_to_geojson(G, direction)

        jobs[job_id]["result"] = geojson
        jobs[job_id].pop("partial", None)
        update(100, "Done!", status="done")

    except Exception as exc:
        jobs[job_id]["error"] = str(exc)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = f"Error: {exc}"
        traceback.print_exc()


def _route_with_host(G, center_node, towards_origin, direction,
                     osrm_host, job_id, jobs, update):
    """Route all nodes using a pre-configured OSRM server."""
    from motorshed import osrm as osrm_module

    _do_routing(G, center_node, towards_origin, direction,
                osrm_module, job_id, jobs, update)


def _route_on_demand(G, lat, lng, radius_km, place,
                     center_node, towards_origin,
                     direction, job_id, jobs, update):
    """Download raw OSM data, spin up a temporary OSRM server, route, then tear down."""
    from local_osrm import LocalOSRM
    from motorshed import osrm as osrm_module

    update(8, "Building local routing server…")

    with LocalOSRM(lat, lng, radius_km=radius_km, place=place,
                   on_status=lambda msg: update(8, msg)) as local:
        # Temporarily override the OSRM host for routing
        original_host = osrm_module.OSRM_HOST
        osrm_module.OSRM_HOST = local.host
        try:
            _do_routing(G, center_node, towards_origin, direction,
                        osrm_module, job_id, jobs, update)
        finally:
            osrm_module.OSRM_HOST = original_host


def _do_routing(G, center_node, towards_origin, direction,
                osrm_module, job_id, jobs, update):
    """Core routing loop — shared by both pre-built and on-demand OSRM."""
    update(10, "Routing all nodes via OSRM…")
    nodes = list(G.nodes())
    total_nodes = len(nodes)
    missing_edges = set()

    N_WORKERS = 8

    def route_node(origin_node):
        """Route a single node to/from center via OSRM."""
        if towards_origin:
            route, transit_time, r = osrm_module.osrm(
                G, origin_node, center_node, mode="driving"
            )
        else:
            route, transit_time, r = osrm_module.osrm(
                G, center_node, origin_node, mode="driving"
            )
        # Filter route to only include nodes in our graph
        route = [n for n in route if n in G]
        return route

    # Process nodes in parallel batches
    batch_size = N_WORKERS * 4
    for batch_start in range(0, total_nodes, batch_size):
        batch_end = min(batch_start + batch_size, total_nodes)
        batch_nodes = [
            n for n in nodes[batch_start:batch_end]
            if not G.nodes[n]["calculated"]
        ]

        # Update progress (10% to 85% range for routing)
        progress = 10 + int(75 * batch_start / total_nodes)
        update(progress,
               f"Routing nodes {batch_start}/{total_nodes}…")

        with concurrent.futures.ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
            future_to_node = {
                executor.submit(route_node, n): n
                for n in batch_nodes
            }

            for future in concurrent.futures.as_completed(future_to_node):
                origin_node = future_to_node[future]
                try:
                    route = future.result()
                    # Increment traffic on every edge along the route
                    if len(route) > 0:
                        accum_traffic = 1
                        for i0, i1 in zip(route[:-1], route[1:]):
                            if not G.nodes[i0]["calculated"]:
                                accum_traffic += 1
                            try:
                                G.edges[i0, i1, 0]["through_traffic"] += accum_traffic
                            except KeyError:
                                missing_edges.add((i0, i1))
                        G.nodes[origin_node]["calculated"] = True
                except Exception as exc:
                    print(f"Error routing node {origin_node}: {exc}")

        # Update progress after each batch completes
        routed = min(batch_end, total_nodes)
        progress = 10 + int(75 * routed / total_nodes)
        pct = int(100 * routed / total_nodes)
        update(progress,
               f"Routing nodes… {routed}/{total_nodes} ({pct}%)")

        # Send partial GeoJSON snapshot every ~5% of progress
        if total_nodes > 0 and (routed % max(1, total_nodes // 20) < batch_size
                                or routed >= total_nodes):
            jobs[job_id]["partial"] = graph_to_geojson(G, direction)


def graph_to_geojson(G, direction: str) -> dict:
    """
    Convert graph G directly to a GeoJSON FeatureCollection.
    Every edge is included — through_traffic is already accumulated on the graph.
    Uses log-scale normalization so low-traffic roads are visually distinct from
    high-traffic ones.
    """
    import math

    # Match the original renderer's normalization: log2(traffic + 2)
    # The +2 prevents very small values from compressing the scale
    min_intensity_ratio = 1.1 / 255  # minimum visible intensity

    # First pass: compute max intensity for normalization
    max_intensity = 0.0
    for _, _, data in G.edges(data=True):
        intensity = math.log2(float(data["through_traffic"]) + 2.0)
        if intensity > max_intensity:
            max_intensity = intensity
    if max_intensity == 0:
        max_intensity = 1.0

    seen = set()
    features = []

    for u, v, data in G.edges(data=True):
        if (u, v) in seen:
            continue
        seen.add((u, v))

        raw_traffic = float(data.get("through_traffic", 0))
        # Normalized intensity matching render_mpl.py
        intensity = math.log2(raw_traffic + 2.0) / max_intensity
        # Apply minimum intensity ratio
        intensity = intensity * (1.0 - min_intensity_ratio) + min_intensity_ratio

        u_data = G.nodes[u]
        v_data = G.nodes[v]

        coords = [
            [float(u_data["lon"]), float(u_data["lat"])],
            [float(v_data["lon"]), float(v_data["lat"])],
        ]

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "traffic": intensity,
                "through_traffic": raw_traffic,
                "highway": str(data.get("highway", "")),
                "direction": direction,
            },
        })

    # Sort by traffic so bright/thick edges render on top of dim ones
    features.sort(key=lambda f: f["properties"]["through_traffic"])

    return {
        "type": "FeatureCollection",
        "features": features,
    }
