/**
 * API client for the Motorshed backend.
 */

const BASE = '/api'

/**
 * Start a new motorshed computation.
 * @returns {Promise<string>} job_id
 */
export async function startCompute({ lat, lng, radiusKm, direction }) {
  const res = await fetch(`${BASE}/compute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lat,
      lng,
      radius_km: radiusKm,
      direction,
    }),
  })
  if (!res.ok) throw new Error(`Failed to start job: ${res.status}`)
  const { job_id } = await res.json()
  return job_id
}

/**
 * Subscribe to job progress via Server-Sent Events.
 *
 * @param {string} jobId
 * @param {function} onUpdate  called with { status, progress, message }
 * @param {function} onResult  called with GeoJSON FeatureCollection when done
 * @param {function} onError   called with error message string
 * @returns {function} cleanup – call to close the SSE connection early
 */
export function subscribeToJob(jobId, { onUpdate, onResult, onError }) {
  const es = new EventSource(`${BASE}/stream/${jobId}`)

  es.onmessage = (event) => {
    let data
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }

    onUpdate?.({ status: data.status, progress: data.progress, message: data.message })

    if (data.status === 'done') {
      es.close()
      onResult?.(data.result)
    } else if (data.status === 'error') {
      es.close()
      onError?.(data.error ?? 'Unknown error')
    }
  }

  es.onerror = () => {
    es.close()
    onError?.('Lost connection to server')
  }

  return () => es.close()
}
