"""FastAPI server module with AI Data Steward Dashboard."""

import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app

from .config import ServerEnv, initialize_environment
from .observability import configure_otel_resource, setup_opentelemetry


from .dashboard.routes import router as dashboard_router


env = initialize_environment(ServerEnv)


configure_otel_resource(
    agent_name=env.agent_name,
    project_id=env.google_cloud_project,
)


AGENT_DIR = os.getenv("AGENT_DIR", str(Path(__file__).resolve().parent.parent))

STATIC_DIR = Path(__file__).resolve().parent / "dashboard" / "static"


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri=env.session_service_uri,
    artifact_service_uri=env.artifact_service_uri,
    memory_service_uri=env.memory_service_uri,
    allow_origins=env.allow_origins_list,
    web=env.serve_web_interface,
    reload_agents=env.reload_agents,
)


app.include_router(dashboard_router)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/steward", include_in_schema=False, response_model=None)
async def serve_dashboard() -> FileResponse | dict[str, str]:
    """Serve the main Data Steward SPA."""
    
   
    index_file = STATIC_DIR / "html" / "index.html"
    
    if index_file.is_file():
        return FileResponse(str(index_file))
    return {"status": "error", "message": f"Dashboard UI not found at {index_file}. API Running."}

@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for container orchestration."""
    return {"status": "ok", "agent": env.agent_name}


def main() -> None:
    """Run the FastAPI server."""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    # Setup telemetry
    setup_opentelemetry(
        project_id=env.google_cloud_project,
        agent_name=env.agent_name,
        log_level=env.log_level,
    )

    # Run the server
    uvicorn.run(
        app,
        host=env.host,
        port=env.port,
    )

if __name__ == "__main__":
    main()