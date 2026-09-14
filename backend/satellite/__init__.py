"""
Satellite module for Phoenix fire confirmation.

Provides satellite-based context and confirmation verdict for fire classifications.

Core components:
- sentinel_client: Sentinel-2 satellite image retrieval
- osm_client: OpenStreetMap facility and land-use queries
- landcover: Land cover analysis and classification
- confirmation: Rules engine for consistency evaluation
- service: Main orchestrator

Example usage:
    from backend.satellite import SatelliteConfirmationService, HotspotInputSchema
    from datetime import datetime
    
    service = SatelliteConfirmationService()
    
    hotspot = HotspotInputSchema(
        latitude=28.6139,
        longitude=77.2090,
        timestamp=datetime.fromisoformat("2026-09-13T14:30:00Z"),
        predicted_class="Industrial Fire",
        classification_confidence=0.87,
    )
    
    result = await service.process_hotspot(hotspot)
    print(result.confirmation)  # CONSISTENT / INCONSISTENT / UNCERTAIN
    print(result.reasons)  # List of supporting reasons
"""

from .confirmation import ConfirmationRulesEngine
from .landcover import LandCoverAnalyzer
from .osm_client import OSMClient, OSMClientImpl
from .schemas import (
    ConfirmationReasonSchema,
    ConfirmationStatusEnum,
    HotspotInputSchema,
    LandCoverContextSchema,
    LandCoverTypeEnum,
    OSMContextSchema,
    PredictedClassEnum,
    SatelliteConfirmationOutputSchema,
    SatelliteConfirmationRequest,
    SatelliteConfirmationResponse,
    SentinelImageInfoSchema,
)
from .sentinel_client import SentinelClient, SentinelClientImpl
from .service import SatelliteConfirmationService

__all__ = [
    # Schemas
    "HotspotInputSchema",
    "SatelliteConfirmationRequest",
    "SatelliteConfirmationResponse",
    "SatelliteConfirmationOutputSchema",
    "SentinelImageInfoSchema",
    "OSMContextSchema",
    "LandCoverContextSchema",
    "ConfirmationReasonSchema",
    # Enums
    "PredictedClassEnum",
    "ConfirmationStatusEnum",
    "LandCoverTypeEnum",
    # Clients
    "SentinelClient",
    "SentinelClientImpl",
    "OSMClient",
    "OSMClientImpl",
    # Analysis
    "LandCoverAnalyzer",
    "ConfirmationRulesEngine",
    # Service
    "SatelliteConfirmationService",
]

__version__ = "0.1.0"
__author__ = "Phoenix Development Team"
__description__ = "Satellite-based fire confirmation module for Phoenix"
