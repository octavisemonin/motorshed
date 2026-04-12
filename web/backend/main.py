"""
Travelshed Web API — FastAPI backend.

Endpoints:
  POST /api/compute          Start a new computation job
  GET  /api/status/{job_id}  Poll job status and progress
  GET  /api/result/{job_id}  Fetch completed GeoJSON result
  GET  /api/stream/{job_id}  Server-Sent Events stream of status updates
"""

import asyncio
import concurrent.futures
import json
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import job_runner

app = FastAPI(title="Travelshed Web API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store. For production, swap with Redis or a database.
jobs: dict = {}

# Thread pool for running blocking travelshed computation off the event loop
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


class ComputeRequest(BaseModel):
    lat: float = Field(..., description="Origin latitude")
    lng: float = Field(..., description="Origin longitude")
    radius_km: float = Field(3.0, ge=0.5, le=20.0, description="Search radius in km")
    direction: str = Field("to", description="'to', 'from'")
    mode: str = Field("driving", description="Routing mode: 'driving', 'cycling', or 'walking'")
    place: str | None = Field(None, description="City/place name (e.g. 'San Francisco, CA'). If set, radius is ignored.")


@app.post("/api/compute")
async def compute(req: ComputeRequest):
    """Start a travelshed computation. Returns a job_id to poll for results."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Queued",
        "result": None,
        "error": None,
    }

    loop = asyncio.get_event_loop()
    jobs[job_id]["place"] = req.place
    loop.run_in_executor(
        _executor,
        job_runner.run_job,
        job_id,
        req.lat,
        req.lng,
        req.radius_km,
        req.direction,
        req.place,
        req.mode,
        jobs,
    )

    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def status(job_id: str):
    """Poll job status: pending | running | done | error."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return {
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "error": job.get("error"),
    }


@app.get("/api/result/{job_id}")
async def result(job_id: str):
    """Fetch the completed GeoJSON result for a finished job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job.get("error", "Unknown error"))
    if job["status"] != "done":
        raise HTTPException(status_code=202, detail="Job not yet complete")
    return job["result"]


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    """
    Server-Sent Events stream. Sends status/progress updates every 500ms
    and the full GeoJSON result once computation finishes.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        while True:
            job = jobs.get(job_id, {})
            payload: dict = {
                "status": job.get("status"),
                "progress": job.get("progress", 0),
                "message": job.get("message", ""),
            }

            finished = job.get("status") in ("done", "error")

            # Include partial results during computation
            if not finished and "partial" in job:
                payload["partial"] = job.pop("partial")

            if finished and job.get("status") == "done":
                payload["result"] = job["result"]
            if finished and job.get("status") == "error":
                payload["error"] = job.get("error")

            yield f"data: {json.dumps(payload)}\n\n"

            if finished:
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
