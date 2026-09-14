"""
Satellite image retrieval routes.

Endpoints for fetching Sentinel-2 imagery and metadata.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from ..satellite.schemas import (
        SatelliteConfirmationRequest,
        SatelliteConfirmationResponse,
    )
    from ..satellite.service import SatelliteConfirmationService
except ImportError:
    from satellite.schemas import (
        SatelliteConfirmationRequest,
        SatelliteConfirmationResponse,
    )
    from satellite.service import SatelliteConfirmationService

router = APIRouter()

# Initialize service
_satellite_service: Optional[SatelliteConfirmationService] = None


def get_service() -> SatelliteConfirmationService:
    """Get or initialize satellite service."""
    global _satellite_service
    if _satellite_service is None:
        _satellite_service = SatelliteConfirmationService()
    return _satellite_service


# ========================
# Response Models
# ========================


class ImageMetadataResponse(BaseModel):
    """Response model for satellite image retrieval."""

    image_url: str = Field(..., description="URL to retrieve the image")
    acquisition_date: datetime = Field(..., description="Date the image was captured")
    cloud_coverage: float = Field(..., description="Cloud coverage percentage")
    bands_available: list[str] = Field(..., description="Available spectral bands")
    resolution_m: int = Field(..., description="Pixel resolution in meters")

    class Config:
        json_schema_extra = {
            "example": {
                "image_url": "s3://copernicus-tiles/sentinel-2/S2A_MSIL2A_20260913.../TCI.tif",
                "acquisition_date": "2026-09-13T05:35:18Z",
                "cloud_coverage": 12.5,
                "bands_available": ["B2", "B3", "B4", "B8", "B11"],
                "resolution_m": 10,
            }
        }


class ImageRetrievalResponse(BaseModel):
    """Complete image retrieval response."""

    success: bool = Field(..., description="Whether retrieval was successful")
    image: Optional[ImageMetadataResponse] = Field(
        None, description="Image metadata if successful"
    )
    message: Optional[str] = Field(None, description="Status or error message")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "image": {
                    "image_url": "s3://copernicus-tiles/sentinel-2/...",
                    "acquisition_date": "2026-09-13T05:35:18Z",
                    "cloud_coverage": 12.5,
                    "bands_available": ["B2", "B3", "B4", "B8", "B11"],
                    "resolution_m": 10,
                },
                "message": "Image retrieved successfully",
            }
        }


# ========================
# Endpoints
# ========================


@router.get(
    "/image",
    response_model=ImageRetrievalResponse,
    summary="Retrieve Sentinel-2 image",
    description="Get Sentinel-2 satellite image for given coordinates and date",
)
async def get_satellite_image(
    latitude: float = Query(
        ...,
        ge=-90,
        le=90,
        description="Latitude of target location (-90 to 90)",
    ),
    longitude: float = Query(
        ...,
        ge=-180,
        le=180,
        description="Longitude of target location (-180 to 180)",
    ),
    timestamp: str = Query(
        ...,
        description="ISO 8601 datetime (e.g., 2026-09-13T14:30:00Z)",
    ),
) -> ImageRetrievalResponse:
    """
    Retrieve Sentinel-2 satellite image for specified coordinates and date.

    The endpoint:
    1. Validates coordinate and timestamp inputs
    2. Searches for cloud-free imagery within ±5 days of the date
    3. Returns image metadata and URL
    4. Caches results to minimize API calls

    **Query Parameters:**
    - `latitude`: Latitude (-90 to 90)
    - `longitude`: Longitude (-180 to 180)
    - `timestamp`: ISO 8601 datetime string

    **Responses:**
    - 200: Image found and returned
    - 404: No suitable imagery found for coordinates/date
    - 422: Invalid input parameters
    - 502: Sentinel Hub API unreachable

    **Example:**
    ```
    GET /api/satellite/image?latitude=28.6139&longitude=77.2090&timestamp=2026-09-13T14:30:00Z
    ```

    **Security:**
    - Sentinel Hub credentials are never exposed
    - Images are retrieved through a secure backend channel
    - All requests are logged (credentials excluded)
    """

    # ========================
    # Input Validation
    # ========================

    # Validate latitude/longitude
    if not (-90 <= latitude <= 90):
        raise HTTPException(
            status_code=422,
            detail=f"Latitude must be between -90 and 90, got {latitude}",
        )
    if not (-180 <= longitude <= 180):
        raise HTTPException(
            status_code=422,
            detail=f"Longitude must be between -180 and 180, got {longitude}",
        )

    # Parse timestamp
    try:
        event_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid timestamp format. Use ISO 8601 (e.g., 2026-09-13T14:30:00Z)",
        )

    # ========================
    # Retrieve Image
    # ========================

    service = get_service()

    try:
        image_info = await service.sentinel.get_latest_image(
            latitude=latitude,
            longitude=longitude,
            timestamp=event_timestamp,
            radius_m=512,
            max_cloud_coverage=50.0,
        )

    except Exception as e:
        # Handle upstream API failures
        error_msg = str(e)
        print(f"Sentinel Hub API error: {error_msg}")

        if "404" in error_msg or "not found" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail="No suitable imagery found for the specified location and date",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail="Sentinel Hub API is unavailable. Please try again later.",
            )

    # ========================
    # Return Response
    # ========================

    if image_info is None:
        return ImageRetrievalResponse(
            success=False,
            image=None,
            message="No suitable cloud-free imagery found for the specified location and date within ±5 days",
        )

    return ImageRetrievalResponse(
        success=True,
        image=ImageMetadataResponse(
            image_url=image_info.image_url,
            acquisition_date=image_info.acquisition_date,
            cloud_coverage=image_info.cloud_coverage,
            bands_available=image_info.bands_available,
            resolution_m=image_info.resolution_m,
        ),
        message="Image retrieved successfully",
    )


@router.get(
    "/status",
    summary="Check satellite service status",
    description="Verify that the satellite service is operational",
)
async def satellite_service_status():
    """Check if satellite service is ready."""
    try:
        service = get_service()
        return {
            "status": "operational",
            "service": "sentinel-2",
            "cache_directory": str(service.sentinel.CACHE_DIR),
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Service unavailable: {str(e)}",
        )


@router.post(
    "/confirm",
    response_model=SatelliteConfirmationResponse,
    summary="Confirm fire hotspot using satellite and geographic context",
    description="Evaluate consistency of a FIRMS hotspot classification against Sentinel-2 imagery, OSM facilities, and land cover.",
)
async def confirm_fire_hotspot(
    request: SatelliteConfirmationRequest,
) -> SatelliteConfirmationResponse:
    """
    Confirm fire detection prediction using multi-source satellite and OSM context.

    Request Body:
    - latitude: float (-90 to 90)
    - longitude: float (-180 to 180)
    - timestamp: ISO 8601 UTC datetime
    - predicted_class: Fire class (e.g. Industrial Fire, Gas Flare, Agricultural Burn, Wildfire, Mining, Unknown)
    - classification_confidence: Original model confidence (0 to 1)

    Returns:
    - Complete confirmation response with evidence, score (0-100), status (CONSISTENT, INCONSISTENT, UNCERTAIN),
      and explainable reasons. Original classification is never modified.
    """
    service = get_service()
    try:
        response = await service.confirm_hotspot(request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Confirmation analysis failed: {str(e)}")
