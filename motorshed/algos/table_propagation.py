"""
Table-based traffic propagation using OSRM transit times.

Instead of routing each node individually (O(N) OSRM route calls), this approach:
1. Calls OSRM Table API to get transit times for all nodes — O(N/100) requests.
2. Builds a next-hop tree: each node's next hop is the neighbor with the smallest
   transit time that is strictly less than the node's own time.
3. Propagates traffic via a single topological pass — O(V+E) local computation.

For a 400-node intersection graph this reduces OSRM calls from ~400 to ~4-8,
giving a 50-100× speedup at the cost of using approximate (greedy) routing.
"""


def build_next_hop_map(G, towards_origin=True):
    """Return {node: next_hop_node} for every node that has a valid next hop.

    A valid next hop is the outgoing neighbor (or incoming, if towards_origin
    is False) whose transit_time is strictly less than the current node's.
    Nodes at the center (transit_time == 0) or unreachable (None) are skipped.
    """
    next_hop = {}
    for node in G.nodes():
        t_node = G.nodes[node].get("transit_time")
        if t_node is None or t_node == 0:
            continue

        candidates = list(G.successors(node)) if towards_origin else list(G.predecessors(node))

        best, best_t = None, t_node
        for nb in candidates:
            t = G.nodes[nb].get("transit_time")
            if t is not None and t < best_t:
                best_t, best = t, nb

        if best is not None:
            next_hop[node] = best

    return next_hop


def propagate_traffic(G, next_hop, towards_origin=True, source_nodes=None):
    """Accumulate through_traffic on edges by summing subtree sizes.

    Only nodes in source_nodes originate 1 unit of traffic; all other nodes
    start at 0 but still pass accumulated upstream traffic through. If
    source_nodes is None, every node originates 1 unit (original behavior).

    Nodes are processed farthest-first so upstream contributions are fully
    accumulated before a node propagates downstream.

    Returns a set of (u, v) pairs for edges that were missing from the graph.
    """
    active = sorted(next_hop, key=lambda n: G.nodes[n].get("transit_time", 0), reverse=True)

    if source_nodes is not None:
        source_set = set(source_nodes)
        node_traffic = {n: (1 if n in source_set else 0) for n in G.nodes()}
    else:
        node_traffic = {n: 1 for n in G.nodes()}

    missing = set()

    for node in active:
        nxt = next_hop[node]
        traffic = node_traffic[node]
        node_traffic[nxt] = node_traffic.get(nxt, 0) + traffic
        if traffic > 0:
            try:
                if towards_origin:
                    G.edges[node, nxt, 0]["through_traffic"] += traffic
                else:
                    G.edges[nxt, node, 0]["through_traffic"] += traffic
            except KeyError:
                missing.add((node, nxt))

    return missing


def run_table_propagation(G, origin_point, osrm_module, towards_origin,
                           osrm_profile, update=None):
    """Update G in-place with through_traffic on every edge.

    Args:
        G:              NetworkX graph with lat/lon on nodes and through_traffic on edges.
        origin_point:   Center node ID (int) or (lat, lon) tuple.
        osrm_module:    Module exposing get_transit_times().
        towards_origin: True → traffic flows toward origin; False → away from it.
        osrm_profile:   OSRM profile string, e.g. 'driving'.
        update:         Optional callback(progress_pct, message) for progress reporting.
    """
    n = len(G.nodes())
    if update:
        update(10, f"Fetching transit times for {n} nodes…")

    # Report progress every ~10% over the 10-60% range during table fetching.
    last_reported = [10]

    def on_chunk(done, total):
        if update is None:
            return
        pct = 10 + int(50 * done / total)
        if pct - last_reported[0] >= 10 or done == total:
            last_reported[0] = pct
            update(pct, f"Fetching transit times… {done}/{total} chunks")

    osrm_module.get_transit_times(G, origin_point,
                                  towards_origin=towards_origin,
                                  profile=osrm_profile,
                                  progress_callback=on_chunk)

    if update:
        update(60, "Building next-hop routing tree…")

    next_hop = build_next_hop_map(G, towards_origin=towards_origin)

    # Only intersection/dead-end nodes originate traffic — same set as _do_routing().
    # Degree-2 waypoints along roads still *pass* accumulated traffic through but
    # don't add their own unit, preventing every residential road from glowing.
    G_undirected = G.to_undirected()
    source_nodes = [nd for nd in G.nodes() if G_undirected.degree(nd) != 2]

    n_valid = sum(1 for nd in G.nodes() if G.nodes[nd].get("transit_time") is not None)
    print(
        f"table_propagation: {n} nodes total, {n_valid} with transit times, "
        f"{len(source_nodes)} source (intersection) nodes, "
        f"{len(next_hop)} with valid next hops"
    )

    if update:
        update(75, f"Propagating traffic from {len(source_nodes)} intersection nodes…")

    missing = propagate_traffic(G, next_hop, towards_origin=towards_origin,
                                source_nodes=source_nodes)

    if update:
        update(85, "Traffic propagation complete.")

    print(f"table_propagation: {len(missing)} edges missing from graph (skipped)")

    return missing
