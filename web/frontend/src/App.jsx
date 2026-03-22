import { useState, useCallback, useRef } from 'react'
import DeckGL from '@deck.gl/react'
import { Map } from 'react-map-gl/maplibre'
import { ScatterplotLayer } from '@deck.gl/layers'
import { startCompute, subscribeToJob } from './api'
import { buildMotorshedLayer } from './MotorshedLayer'

// Map styles — no API key required
const MAP_STYLES = {
  dark: 'https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json',
  light: 'https://basemaps.cartocdn.com/gl/positron-nolabels-gl-style/style.json',
}

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
  const [boundaryMode, setBoundaryMode] = useState('radius') // 'radius' or 'place'
  const [placeName, setPlaceName] = useState('')
  const [theme, setTheme] = useState('dark') // 'dark' or 'light'
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
        place: boundaryMode === 'place' && placeName.trim() ? placeName.trim() : null,
      })
    } catch (err) {
      setJobState({ status: 'error', progress: 0, message: '', error: err.message })
      return
    }

    const cancel = subscribeToJob(jobId, {
      onUpdate: ({ status, progress, message }) => {
        setJobState({ status, progress, message, error: null })
      },
      onPartial: (partial) => {
        setGeojson(partial)
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
  }, [origin, radiusKm, direction, boundaryMode, placeName])

  // Build deck.gl layers
  const layers = []

  // Motorshed road-traffic layer
  if (geojson) {
    layers.push(buildMotorshedLayer(geojson, direction, theme))
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
        getFillColor: theme === 'dark' ? [255, 255, 255, 220] : [30, 30, 30, 220],
        getLineColor: theme === 'dark' ? [224, 96, 58, 255] : [20, 60, 150, 255],
        stroked: true,
        lineWidthMinPixels: 3,
        pickable: false,
      })
    )
  }

  const isComputing = jobState?.status === 'running' || jobState?.status === 'pending'
  const featureCount = geojson?.features?.length ?? 0

  return (
    <div
      className={theme === 'light' ? 'app-root light-theme' : 'app-root'}
      style={{ width: '100vw', height: '100vh', position: 'relative' }}
    >
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => setViewState(vs)}
        controller={true}
        layers={layers}
        onClick={handleMapClick}
        getCursor={({ isDragging }) => isDragging ? 'grabbing' : 'crosshair'}
      >
        <Map mapStyle={MAP_STYLES[theme]} />
      </DeckGL>

      {/* ---- Sidebar ---- */}
      <div className="sidebar">
        <h1>Motorshed</h1>
        <p className="tagline">Traffic routing visualizer</p>

        <div className="field">
          <label>Boundary</label>
          <div className="toggle-group">
            <button
              className={boundaryMode === 'radius' ? 'active' : ''}
              onClick={() => setBoundaryMode('radius')}
            >
              Radius
            </button>
            <button
              className={boundaryMode === 'place' ? 'active' : ''}
              onClick={() => setBoundaryMode('place')}
            >
              City / Place
            </button>
          </div>
        </div>

        {boundaryMode === 'radius' ? (
          <div className="field">
            <label>
              Radius
              <span>{radiusKm} km</span>
            </label>
            <input
              type="range"
              min={1}
              max={20}
              step={0.5}
              value={radiusKm}
              onChange={e => setRadiusKm(Number(e.target.value))}
            />
          </div>
        ) : (
          <div className="field">
            <label>Place name</label>
            <input
              type="text"
              className="place-input"
              placeholder="e.g. San Francisco, CA"
              value={placeName}
              onChange={e => setPlaceName(e.target.value)}
            />
          </div>
        )}

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

        <div className="field">
          <label>Theme</label>
          <div className="toggle-group">
            <button
              className={theme === 'dark' ? 'active' : ''}
              onClick={() => setTheme('dark')}
            >
              Dark
            </button>
            <button
              className={theme === 'light' ? 'active' : ''}
              onClick={() => setTheme('light')}
            >
              Light
            </button>
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
