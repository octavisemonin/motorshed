/**
 * deck.gl PathLayer for the motorshed road-traffic visualization.
 * Uses the magma colormap (matching the CLI output) to color roads by traffic.
 */

import { PathLayer } from '@deck.gl/layers'

/**
 * Magma colormap: 8 control points sampled from matplotlib's magma.
 * Each entry: [t, r, g, b]  (t in [0,1], rgb in [0,255])
 */
const MAGMA = [
  [0.000,   0,   0,   4],
  [0.143,  28,  16,  68],
  [0.286,  79,  18, 123],
  [0.429, 129,  37, 129],
  [0.571, 181,  54, 122],
  [0.714, 229,  80, 100],
  [0.857, 251, 135,  97],
  [1.000, 252, 253, 191],
]

/**
 * Map a normalised traffic value [0,1] to an RGBA color using the magma colormap.
 * @param {number} t  normalised traffic in [0, 1]
 * @returns {[number, number, number, number]}
 */
function magmaColor(t) {
  const v = Math.max(0, Math.min(1, t))

  // Find the two surrounding control points
  for (let i = 0; i < MAGMA.length - 1; i++) {
    const [t0, r0, g0, b0] = MAGMA[i]
    const [t1, r1, g1, b1] = MAGMA[i + 1]
    if (v <= t1) {
      const f = (v - t0) / (t1 - t0)
      const alpha = 255
      return [
        Math.round(r0 + f * (r1 - r0)),
        Math.round(g0 + f * (g1 - g0)),
        Math.round(b0 + f * (b1 - b0)),
        alpha,
      ]
    }
  }
  return [252, 253, 191, 255]
}

/**
 * Build a deck.gl PathLayer from a motorshed GeoJSON FeatureCollection.
 *
 * @param {object} geojson  GeoJSON FeatureCollection with properties.traffic and .through_traffic
 * @param {string} direction  'to' or 'from' (for layer ID uniqueness)
 * @returns {PathLayer}
 */
export function buildMotorshedLayer(geojson, direction) {
  return new PathLayer({
    id: `motorshed-paths-${direction}`,
    data: geojson.features,

    // GeoJSON coordinates are already [lng, lat]
    getPath: d => d.geometry.coordinates,

    // Color by normalised traffic through the magma colormap.
    // Low-traffic roads fade to near-black; high-traffic roads glow yellow.
    getColor: d => magmaColor(d.properties.traffic),

    // Width scales with normalized traffic: thin for low, thick for high
    getWidth: d => 0.3 + d.properties.traffic * 2.5,
    widthUnits: 'pixels',
    widthMinPixels: 0.3,
    widthMaxPixels: 3.5,
    widthScale: 1,

    pickable: false,
    jointRounded: true,
    capRounded: true,

    // Re-render when data changes
    updateTriggers: {
      getColor: [direction],
    },
  })
}
