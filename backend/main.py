"""
FastAPI main application for Phoenix fire confirmation system.

Exposes satellite image retrieval and fire confirmation endpoints.
"""

from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Load environment variables
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Create FastAPI app
app = FastAPI(
    title="Phoenix",
    description="Fire detection and confirmation system",
    version="0.1.0",
)

# Add CORS middleware to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict to frontend domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========================
# Health Check
# ========================


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "phoenix"}


# ========================
# Import Routes
# ========================

try:
    from .routes import satellite
    app.include_router(satellite.router, prefix="/api/satellite", tags=["Satellite"])
except ImportError:
    # Fallback for direct execution
    from routes import satellite
    app.include_router(satellite.router, prefix="/api/satellite", tags=["Satellite"])


# ========================
# Error Handlers
# ========================


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle validation errors."""
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request, exc):
    """Handle unexpected errors."""
    print(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
