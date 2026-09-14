"""
Pydantic schemas for satellite module input/output contracts.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PredictedClassEnum(str, Enum):
    """Enum for predicted fire classifications."""
    INDUSTRIAL_FIRE = "Industrial Fire"
    GAS_FLARE = "Gas Flare"
    AGRICULTURAL_BURN = "Agricultural Burn"
    CROPLAND_FIRE = "Cropland Fire"
    WILDFIRE = "Wildfire"
    FOREST_FIRE = "Forest Fire"
    MINING = "Mining"
    UNKNOWN = "Unknown"
    UNCERTAIN = "Uncertain"


class ConfirmationStatusEnum(str, Enum):
    """Enum for confirmation verdict."""
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    UNCERTAIN = "UNCERTAIN"


class LandCoverTypeEnum(str, Enum):
    """Enum for land cover classifications."""
    INDUSTRIAL = "industrial"
    BUILT_UP = "built_up"
    CROPLAND = "crop"
    FOREST = "forest"
    URBAN = "urban"
    WATER = "water"
    BARREN = "barren"
    BARE = "bare"
    GRASSLAND = "grassland"
    OTHER = "other"


class HotspotInputSchema(BaseModel):
    """
    Input schema: FIRMS hotspot data to be confirmed.
    
    This is the contract between FIRMS detector and satellite confirmation module.
    The satellite module will never modify these values.
    """
    latitude: float = Field(..., description="Latitude of detected hotspot")
    longitude: float = Field(..., description="Longitude of detected hotspot")
    timestamp: datetime = Field(..., description="UTC timestamp of detection")
    predicted_class: PredictedClassEnum = Field(..., description="Initial classification from FIRMS")
    classification_confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="Confidence score of initial classification (0-1)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "latitude": 28.6139,
                "longitude": 77.2090,
                "timestamp": "2026-09-13T14:30:00Z",
                "predicted_class": "Industrial Fire",
                "classification_confidence": 0.87
            }
        }


class SentinelImageInfoSchema(BaseModel):
    """Information about retrieved Sentinel-2 image."""
    image_url: str = Field(..., description="URL to Sentinel-2 satellite image")
    acquisition_date: datetime = Field(..., description="Date image was captured")
    cloud_coverage: float = Field(
        ..., 
        ge=0.0, 
        le=100.0,
        description="Cloud coverage percentage"
    )
    bands_available: List[str] = Field(
        ..., 
        description="List of available bands (B2-B12, SCL, etc.)"
    )
    resolution_m: int = Field(..., description="Pixel resolution in meters")

    class Config:
        json_schema_extra = {
            "example": {
                "image_url": "https://example.com/sentinel2/image.tif",
                "acquisition_date": "2026-09-13T10:00:00Z",
                "cloud_coverage": 15.5,
                "bands_available": ["B2", "B3", "B4", "B8", "B11"],
                "resolution_m": 10
            }
        }


class OSMContextSchema(BaseModel):
    """Context information from OpenStreetMap."""
    nearby_facilities: List[dict] = Field(
        default_factory=list,
        description="List of nearby industrial/agricultural facilities"
    )
    land_use_categories: List[str] = Field(
        default_factory=list,
        description="Land use types detected within radius"
    )
    distance_to_nearest_facility_m: Optional[float] = Field(
        default=None,
        description="Distance to nearest relevant facility in meters"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "nearby_facilities": [
                    {"type": "industrial", "name": "Steel Plant", "distance_m": 250},
                    {"type": "warehouse", "name": "Logistics Hub", "distance_m": 450}
                ],
                "land_use_categories": ["industrial", "commercial"],
                "distance_to_nearest_facility_m": 250
            }
        }


class LandCoverContextSchema(BaseModel):
    """Land cover analysis from satellite imagery."""
    dominant_land_cover: LandCoverTypeEnum = Field(..., description="Primary land cover type")
    land_cover_distribution: dict = Field(
        default_factory=dict,
        description="Percentage distribution of land cover types within analysis radius"
    )
    ndvi_value: Optional[float] = Field(
        default=None, 
        ge=-1.0, 
        le=1.0,
        description="Normalized Difference Vegetation Index"
    )
    built_up_percentage: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of built-up area"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "dominant_land_cover": "industrial",
                "land_cover_distribution": {
                    "industrial": 65.3,
                    "urban": 25.4,
                    "barren": 9.3
                },
                "ndvi_value": 0.12,
                "built_up_percentage": 90.7
            }
        }


class ConfirmationReasonSchema(BaseModel):
    """Single reason for confirmation verdict."""
    category: str = Field(..., description="Category: facility, landcover, vegetation, or other")
    description: str = Field(..., description="Human-readable reason")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in this reason (0-1)"
    )


class SatelliteConfirmationOutputSchema(BaseModel):
    """
    Output schema: Satellite confirmation result.
    
    Contains satellite context, confirmation verdict, and reasoning.
    Original classification is preserved without modification.
    """
    image_info: SentinelImageInfoSchema = Field(..., description="Sentinel-2 image metadata")
    osm_context: OSMContextSchema = Field(..., description="OpenStreetMap context")
    landcover_context: LandCoverContextSchema = Field(..., description="Land cover analysis")
    
    # Original classification preserved
    predicted_class: PredictedClassEnum = Field(..., description="Original predicted class (unchanged)")
    original_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Original classification confidence (unchanged)"
    )
    
    # Confirmation verdict
    confirmation: ConfirmationStatusEnum = Field(..., description="Confirmation status")
    confirmation_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in confirmation verdict (0-1)"
    )
    reasons: List[ConfirmationReasonSchema] = Field(
        ...,
        description="List of reasons supporting the confirmation verdict"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "image_info": {
                    "image_url": "https://example.com/sentinel2/image.tif",
                    "acquisition_date": "2026-09-13T10:00:00Z",
                    "cloud_coverage": 15.5,
                    "bands_available": ["B2", "B3", "B4", "B8", "B11"],
                    "resolution_m": 10
                },
                "osm_context": {
                    "nearby_facilities": [
                        {"type": "industrial", "name": "Steel Plant", "distance_m": 250}
                    ],
                    "land_use_categories": ["industrial"],
                    "distance_to_nearest_facility_m": 250
                },
                "landcover_context": {
                    "dominant_land_cover": "industrial",
                    "land_cover_distribution": {"industrial": 65.3, "urban": 25.4},
                    "ndvi_value": 0.12,
                    "built_up_percentage": 90.7
                },
                "predicted_class": "Industrial Fire",
                "original_confidence": 0.87,
                "confirmation": "CONSISTENT",
                "confirmation_confidence": 0.92,
                "reasons": [
                    {
                        "category": "facility",
                        "description": "Industrial facility detected within 500m",
                        "confidence": 1.0
                    },
                    {
                        "category": "landcover",
                        "description": "Area is predominantly built-up (90.7%)",
                        "confidence": 0.95
                    },
                    {
                        "category": "vegetation",
                        "description": "No significant cropland detected (NDVI: 0.12)",
                        "confidence": 0.85
                    }
                ]
            }
        }


class SatelliteConfirmationRequest(BaseModel):
    """
    Request schema for POST /api/satellite/confirm.
    
    Accepts FIRMS hotspot coordinates, detection timestamp, and original classification.
    """
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude of detected hotspot (-90 to 90)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude of detected hotspot (-180 to 180)")
    timestamp: datetime = Field(..., description="UTC timestamp of hotspot detection")
    predicted_class: str = Field(..., description="Predicted fire class (e.g., Industrial Fire, Gas Flare, Agricultural Burn, Wildfire, Mining, Unknown)")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Original model classification confidence (0 to 1)")

    class Config:
        json_schema_extra = {
            "example": {
                "latitude": 28.6139,
                "longitude": 77.2090,
                "timestamp": "2026-09-13T14:30:00Z",
                "predicted_class": "Industrial Fire",
                "classification_confidence": 0.87,
            }
        }


class SatelliteConfirmationResponse(BaseModel):
    """
    Response schema for POST /api/satellite/confirm.
    
    Contains hotspot coordinates, original classification (unaltered),
    Sentinel-2 image metadata, nearby facilities, land-cover summary,
    confirmation status, score (0-100), reasons, and evidence.
    """
    latitude: float = Field(..., description="Hotspot latitude")
    longitude: float = Field(..., description="Hotspot longitude")
    timestamp: datetime = Field(..., description="Hotspot event timestamp")
    predicted_class: str = Field(..., description="Original predicted class (preserved unchanged)")
    classification_confidence: float = Field(..., description="Original classification confidence (preserved unchanged)")
    image_url: Optional[str] = Field(None, description="Sentinel-2 image URL or reference")
    acquisition_date: Optional[datetime] = Field(None, description="Sentinel-2 acquisition date")
    cloud_coverage: Optional[float] = Field(None, description="Sentinel-2 cloud coverage percentage")
    nearby_facilities: List[dict] = Field(default_factory=list, description="Nearby facilities detected via OSM")
    landcover_summary: dict = Field(default_factory=dict, description="Surrounding land-cover percentages")
    confirmation: ConfirmationStatusEnum = Field(..., description="Confirmation verdict: CONSISTENT, INCONSISTENT, or UNCERTAIN")
    confirmation_score: float = Field(..., ge=0.0, le=100.0, description="Confirmation confidence score (0 to 100)")
    reasons: List[str] = Field(default_factory=list, description="Explainable reasons supporting the confirmation verdict")
    evidence: dict = Field(default_factory=dict, description="Structured dictionary of driving evidence")
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of confirmation analysis")

    class Config:
        json_schema_extra = {
            "example": {
                "latitude": 28.6139,
                "longitude": 77.2090,
                "timestamp": "2026-09-13T14:30:00Z",
                "predicted_class": "Industrial Fire",
                "classification_confidence": 0.87,
                "image_url": "s3://copernicus-tiles/sentinel-2/.../TCI.tif",
                "acquisition_date": "2026-09-13T05:35:18Z",
                "cloud_coverage": 12.5,
                "nearby_facilities": [
                    {"name": "Refinery", "type": "industrial", "distance_m": 243}
                ],
                "landcover_summary": {
                    "built_up": 74.0,
                    "cropland": 4.0,
                    "vegetation": 8.0,
                    "bare": 14.0
                },
                "confirmation": "CONSISTENT",
                "confirmation_score": 90.0,
                "reasons": [
                    "Industrial facility located 243m from hotspot",
                    "Built-up/industrial land dominates the surrounding area (74.0%)",
                    "Satellite image available with acceptable cloud coverage (12.5%)"
                ],
                "evidence": {
                    "has_nearby_industrial_facility": True,
                    "nearest_facility_distance_m": 243,
                    "built_up_percentage": 74.0,
                    "cropland_percentage": 4.0,
                    "vegetation_percentage": 8.0,
                    "satellite_available": True,
                    "cloud_coverage": 12.5
                },
                "analysis_timestamp": "2026-09-13T22:30:00Z"
            }
        }
