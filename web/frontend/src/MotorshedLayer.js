/**
 * deck.gl PathLayer for the motorshed road-traffic visualization.
 * Supports dark mode (magma colormap) and light mode (white-to-blue).
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
 * Light mode colormap: white → light blue → dark blue → black
 */
const LIGHT = [
  [0.000, 220, 220, 230],
  [0.250, 140, 170, 210],
  [0.500,  60, 100, 180],
  [0.750,  20,  50, 130],
  [1.000,   5,  10,  40],
]

/**
 * Interpolate through a colormap.
 * @param {Array} cmap  Array of [t, r, g, b] control points
 * @param {number} t  normalised value in [0, 1]
 * @returns {[number, number, number, number]}
 */
function interpolateColor(cmap, t) {
  const v = Math.max(0, Math.min(1, t))

  for (let i = 0; i < cmap.length - 1; i++) {
    const [t0, r0, g0, b0] = cmap[i]
    const [t1, r1, g1, b1] = cmap[i + 1]
    if (v <= t1) {
      const f = (v - t0) / (t1 - t0)
      return [
        Math.round(r0 + f * (r1 - r0)),
        Math.round(g0 + f * (g1 - g0)),
        Math.round(b0 + f * (b1 - b0)),
        255,
      ]
    }
  }
  const last = cmap[cmap.length - 1]
  return [last[1], last[2], last[3], 255]
}

/**
 * Build a deck.gl PathLayer from a motorshed GeoJSON FeatureCollection.
 *
 * @param {object} geojson  GeoJSON FeatureCollection with properties.traffic and .through_traffic
 * @param {string} direction  'to' or 'from' (for layer ID uniqueness)
 * @param {string} theme  'dark' or 'light'
 * @returns {PathLayer}
 */
export function buildMotorshedLayer(geojson, direction, theme = 'dark') {
  const cmap = theme === 'light' ? LIGHT : MAGMA

  return new PathLayer({
    id: `motorshed-paths-${direction}`,
    data: geojson.features,

    // GeoJSON coordinates are already [lng, lat]
    getPath: d => d.geometry.coordinates,

    // Color by normalised traffic through the selected colormap
    getColor: d => interpolateColor(cmap, d.properties.traffic),

    // Width scales with normalized traffic: thin for low, thick for high
    getWidth: d => 0.3 + d.properties.traffic * 2.5,
    widthUnits: 'pixels',
    widthMinPixels: 0.3,
    widthMaxPixels: 3.5,
    widthScale: 1,

    pickable: false,
    jointRounded: true,
    capRounded: true,

    // Re-render when data or theme changes
    updateTriggers: {
      getColor: [direction, theme],
    },
  })
}
