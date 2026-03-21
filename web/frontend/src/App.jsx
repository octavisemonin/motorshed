import { useState, useCallback, useRef } from 'react'
import DeckGL from '@deck.gl/react'
import { Map } from 'react-map-gl/maplibre'
import { ScatterplotLayer } from '@deck.gl/layers'
import { startCompute, subscribeToJob } from './api'
import { buildMotorshedLayer } from './MotorshedLayer'

// Free dark map style — no API key required
const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

const INITIAL_VIEW = {
  longitude: -122.42,
  latitude: 37.78,
  zoom: 12,
  pitch: 0,
  bearing: 0,
}

export default function App() {
  const [viewState, setViewState] = useState(INITIAL_VIEW)
  const [origin, setOrigin] = useState(null)       // { lat, lng }
  const [radiusKm, setRadiusKm] = useState(3)
  const [direction, setDirection] = useState('to')
  const [jobState, setJobState] = useState(null)   // { status, progress, message, error }
  const [geojson, setGeojson] = useState(null)

  const cancelRef = useRef(null)

  const handleMapClick = useCallback((info) => {
    if (!info.coordinate) return
    const [lng, lat] = info.coordinate
    setOrigin({ lat, lng })
    // Clear previous result when origin changes
    setGeojson(null)
    setJobState(null)
  }, [])

  const handleCompute = useCallback(async () => {
    if (!origin) return

    // Cancel any in-flight job
    cancelRef.current?.()
    setGeojson(null)
    setJobState({ status: 'pending', progress: 0, message: 'Starting…', error: null })

    let jobId
    try {
      jobId = await startCompute({
        lat: origin.lat,
        lng: origin.lng,
        radiusKm,
        direction,
      })
    } catch (err) {
      setJobState({ status: 'error', progress: 0, message: '', error: err.message })
      return
    }

    const cancel = subscribeToJob(jobId, {
      onUpdate: ({ status, progress, message }) => {
        setJobState({ status, progress, message, error: null })
      },
      onResult: (result) => {
        setGeojson(result)
        setJobState(prev => ({ ...prev, status: 'done' }))
      },
      onError: (errMsg) => {
        setJobState({ status: 'error', progress: 0, message: '', error: errMsg })
      },
    })
    cancelRef.current = cancel
  }, [origin, radiusKm, direction])

  // Build deck.gl layers
  const layers = []

  // Motorshed road-traffic layer
  if (geojson) {
    layers.push(buildMotorshedLayer(geojson, direction))
  }

  // Origin marker
  if (origin) {
    layers.push(
      new ScatterplotLayer({
        id: 'origin-marker',
        data: [origin],
        getPosition: d => [d.lng, d.lat],
        getRadius: 60,
        radiusUnits: 'meters',
        getFillColor: [255, 255, 255, 220],
        getLineColor: [224, 96, 58, 255],
        stroked: true,
        lineWidthMinPixels: 3,
        pickable: false,
      })
    )
  }

  const isComputing = jobState?.status === 'running' || jobState?.status === 'pending'
  const featureCount = geojson?.features?.length ?? 0

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => setViewState(vs)}
        controller={true}
        layers={layers}
        onClick={handleMapClick}
        getCursor={({ isDragging }) => isDragging ? 'grabbing' : 'crosshair'}
      >
        <Map mapStyle={MAP_STYLE} />
      </DeckGL>

      {/* ---- Sidebar ---- */}
      <div className="sidebar">
        <h1>Motorshed</h1>
        <p className="tagline">Traffic routing visualizer</p>

        <div className="field">
          <label>
            Radius
            <span>{radiusKm} km</span>
          </label>
          <input
            type="range"
            min={1}
            max={10}
            step={0.5}
            value={radiusKm}
            onChange={e => setRadiusKm(Number(e.target.value))}
          />
        </div>

        <div className="field">
          <label>Direction</label>
          <div className="toggle-group">
            {['to', 'from'].map(d => (
              <button
                key={d}
                className={direction === d ? 'active' : ''}
                onClick={() => setDirection(d)}
              >
                {d === 'to' ? 'To origin' : 'From origin'}
              </button>
            ))}
          </div>
        </div>

        <button
          className="compute-btn"
          onClick={handleCompute}
          disabled={!origin || isComputing}
        >
          {isComputing ? 'Computing…' : 'Compute Motorshed'}
        </button>

        <p className="hint">
          {origin
            ? `Origin: ${origin.lat.toFixed(4)}, ${origin.lng.toFixed(4)}`
            : 'Click anywhere on the map to set origin'}
        </p>

        {featureCount > 0 && (
          <div className="stats-panel">
            <strong>{featureCount.toLocaleString()}</strong> road segments rendered
            <br />
            Direction: <strong>{direction === 'to' ? 'routes to origin' : 'routes from origin'}</strong>
          </div>
        )}
      </div>

      {/* ---- Progress overlay ---- */}
      {jobState && jobState.status !== 'done' && (
        <div className="progress-overlay">
          <div className="progress-msg">{jobState.message}</div>
          <div className="progress-bar-track">
            <div
              className="progress-bar-fill"
              style={{ width: `${jobState.progress}%` }}
            />
          </div>
          {jobState.error && (
            <div className="error-msg">{jobState.error}</div>
          )}
        </div>
      )}
    </div>
  )
}
