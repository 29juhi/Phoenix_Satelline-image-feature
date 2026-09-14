"""
Satellite confirmation service.

Main orchestrator that:
1. Accepts FIRMS hotspot input
2. Fetches Sentinel-2 imagery and spectral data
3. Queries OSM for facility/land-use context
4. Analyzes land cover composition
5. Applies confirmation rules
6. Returns verdict with reasons

Never modifies original classification.
"""

from datetime import datetime, timezone
from typing import Optional

from .confirmation import ConfirmationRulesEngine
from .landcover import LandCoverAnalyzer
from .osm_client import OSMClient, OSMClientImpl
from .schemas import (
    ConfirmationStatusEnum,
    HotspotInputSchema,
    SatelliteConfirmationOutputSchema,
    SatelliteConfirmationRequest,
    SatelliteConfirmationResponse,
    SentinelImageInfoSchema,
)
from .sentinel_client import SentinelClient, SentinelClientImpl


class SatelliteConfirmationService:
    """
    Service orchestrating satellite-based fire confirmation workflow.

    Stateless service that processes hotspots through the full pipeline:
    Sentinel-2 → OSM → Land Cover Analysis → Confirmation Rules → Output
    """

    def __init__(
        self,
        sentinel_client: Optional[SentinelClient] = None,
        osm_client: Optional[OSMClient] = None,
    ):
        """
        Initialize service with external clients.

        Args:
            sentinel_client: Sentinel-2 image client (default: SentinelClientImpl)
            osm_client: OpenStreetMap client (default: OSMClientImpl)
        """
        self.sentinel = sentinel_client or SentinelClientImpl()
        self.osm = osm_client or OSMClientImpl()
        self.landcover_analyzer = LandCoverAnalyzer()
        self.confirmation_engine = ConfirmationRulesEngine()

    async def process_hotspot(
        self,
        hotspot: HotspotInputSchema,
        analysis_radius_m: int = 1000,
    ) -> SatelliteConfirmationOutputSchema:
        """
        Process a single FIRMS hotspot through confirmation pipeline.

        Pipeline:
        1. get_sentinel_image() → SentinelImageInfoSchema
        2. get_sentinel_spectral_indices() → dict
        3. get_sentinel_built_up_mask() → dict
        4. get_osm_context() → OSMContextSchema
        5. create_landcover_context() → LandCoverContextSchema
        6. evaluate_prediction() → confirmation status + reasons
        7. package results → SatelliteConfirmationOutputSchema

        Args:
            hotspot: Input hotspot from FIRMS
            analysis_radius_m: Radius for context analysis in meters

        Returns:
            Complete confirmation output with context and verdict

        Raises:
            Exception: If any pipeline step fails (to be caught upstream)
        """
        # Stage 1: Sentinel-2 image and spectral analysis
        sentinel_image = await self._get_sentinel_image(hotspot, analysis_radius_m)
        sentinel_indices = await self._get_sentinel_spectral_indices(hotspot)
        sentinel_built_up = await self._get_sentinel_built_up_mask(
            hotspot, analysis_radius_m
        )

        # Stage 2: OSM context
        osm_context = await self.osm.get_full_osm_context(
            hotspot.latitude,
            hotspot.longitude,
            analysis_radius_m,
        )

        # Stage 3: Land cover analysis
        landcover_context = await self.landcover_analyzer.create_landcover_context(
            hotspot.latitude,
            hotspot.longitude,
            sentinel_indices,
            sentinel_built_up,
            osm_context.nearby_facilities,
            {cat: 0 for cat in osm_context.land_use_categories},  # TODO: get actual %
        )

        # Stage 4: Confirmation rules
        confirmation_status, confirmation_confidence, reasons = (
            await self.confirmation_engine.evaluate_prediction(
                hotspot.predicted_class,
                hotspot.classification_confidence,
                osm_context,
                landcover_context,
                sentinel_image=sentinel_image,
            )
        )

        # Stage 5: Package output
        return SatelliteConfirmationOutputSchema(
            image_info=sentinel_image,
            osm_context=osm_context,
            landcover_context=landcover_context,
            predicted_class=hotspot.predicted_class,  # Preserved unchanged
            original_confidence=hotspot.classification_confidence,  # Preserved unchanged
            confirmation=confirmation_status,
            confirmation_confidence=confirmation_confidence,
            reasons=reasons,
        )

    async def _get_sentinel_image(
        self,
        hotspot: HotspotInputSchema,
        radius_m: int,
    ) -> SentinelImageInfoSchema:
        """
        Retrieve Sentinel-2 image information.

        Args:
            hotspot: Hotspot input with coordinates and timestamp
            radius_m: Search radius around hotspot

        Returns:
            Sentinel image metadata and URL

        Raises:
            Exception: If image retrieval fails
        """
        image = await self.sentinel.get_latest_image(
            hotspot.latitude,
            hotspot.longitude,
            hotspot.timestamp,
            radius_m=radius_m,
        )
        if image is None:
            raise ValueError(
                f"Could not retrieve Sentinel-2 image for {hotspot.latitude}, "
                f"{hotspot.longitude} near {hotspot.timestamp}"
            )
        return image

    async def _get_sentinel_spectral_indices(
        self,
        hotspot: HotspotInputSchema,
    ) -> Optional[dict]:
        """
        Calculate spectral indices from Sentinel-2 bands.

        Args:
            hotspot: Hotspot input with coordinates and timestamp

        Returns:
            Dict of spectral indices or None if unavailable
        """
        indices = await self.sentinel.get_spectral_indices(
            hotspot.latitude,
            hotspot.longitude,
            hotspot.timestamp,
        )
        return indices

    async def _get_sentinel_built_up_mask(
        self,
        hotspot: HotspotInputSchema,
        radius_m: int,
    ) -> Optional[dict]:
        """
        Get built-up area mask and statistics.

        Args:
            hotspot: Hotspot input with coordinates and timestamp
            radius_m: Analysis radius

        Returns:
            Built-up mask dict or None if unavailable
        """
        mask = await self.sentinel.get_built_up_mask(
            hotspot.latitude,
            hotspot.longitude,
            hotspot.timestamp,
            radius_m=radius_m,
        )
        return mask

    async def batch_process_hotspots(
        self,
        hotspots: list[HotspotInputSchema],
        analysis_radius_m: int = 1000,
    ) -> list[SatelliteConfirmationOutputSchema]:
        """
        Process multiple hotspots in sequence.

        TODO: Implement parallel processing if I/O allows.

        Args:
            hotspots: List of hotspot inputs
            analysis_radius_m: Analysis radius for each hotspot

        Returns:
            List of confirmation outputs in same order as inputs

        Raises:
            Exception: If any hotspot processing fails (currently stops pipeline)
        """
        results = []
        for hotspot in hotspots:
            result = await self.process_hotspot(hotspot, analysis_radius_m)
            results.append(result)
        return results

    async def confirm_hotspot(
        self,
        request: SatelliteConfirmationRequest,
        analysis_radius_m: int = 1000,
    ) -> SatelliteConfirmationResponse:
        """
        Orchestrate complete Phoenix Feature 12 confirmation pipeline.

        Pipeline (Steps 13 & 14):
        1. Validate hotspot coordinates and timestamp.
        2. Request the best available Sentinel-2 image around the hotspot.
        3. Query OSM for nearby industrial/context features.
        4. Retrieve/compute surrounding land-cover information.
        5. Pass all evidence to the rule-based confirmation engine.
        6. Return a single structured SatelliteConfirmationResponse.

        The original classification is never overwritten.
        Graceful partial failure handling:
        - If Sentinel is unavailable, continue with OSM/context and mark satellite evidence unavailable.
        - If OSM is unavailable, continue with satellite/land-cover evidence.
        - If all external sources fail, return clear UNCERTAIN response rather than crashing.

        Args:
            request: SatelliteConfirmationRequest
            analysis_radius_m: Radius in meters for buffer analysis

        Returns:
            SatelliteConfirmationResponse with coordinates, classification, image, facilities,
            landcover summary, verdict, score, reasons, and evidence.
        """
        # 1. Validate coordinates
        if not (-90.0 <= request.latitude <= 90.0):
            raise ValueError(f"Latitude must be between -90 and 90, got {request.latitude}")
        if not (-180.0 <= request.longitude <= 180.0):
            raise ValueError(f"Longitude must be between -180 and 180, got {request.longitude}")

        sentinel_image = None
        sentinel_failed = False
        sentinel_indices = None

        # 2. Request Sentinel-2 image
        try:
            sentinel_image = await self.sentinel.get_latest_image(
                latitude=request.latitude,
                longitude=request.longitude,
                timestamp=request.timestamp,
                radius_m=512,
                max_cloud_coverage=50.0,
            )
        except Exception as e:
            sentinel_failed = True
            print(f"Warning: Sentinel-2 image retrieval failed: {e}")

        try:
            sentinel_indices = await self.sentinel.get_spectral_indices(
                latitude=request.latitude,
                longitude=request.longitude,
                timestamp=request.timestamp,
            )
        except Exception:
            pass

        # 3. Query OSM for nearby context features
        osm_failed = False
        nearby_facilities = []
        land_use_dict = {}

        try:
            osm_context = await self.osm.get_full_osm_context(
                latitude=request.latitude,
                longitude=request.longitude,
                radius_m=analysis_radius_m,
            )
            nearby_facilities = osm_context.nearby_facilities
            land_use_dict = {cat: 1 for cat in osm_context.land_use_categories}
        except Exception as e:
            osm_failed = True
            print(f"Warning: OSM query failed: {e}")

        # 4. Compute surrounding land-cover distribution
        try:
            landcover_distribution = await self.landcover_analyzer.get_landcover_distribution(
                latitude=request.latitude,
                longitude=request.longitude,
                sentinel_indices=sentinel_indices,
                osm_facilities=nearby_facilities,
                osm_land_use=land_use_dict,
            )
        except Exception as e:
            print(f"Warning: Land cover analysis failed: {e}")
            landcover_distribution = {
                "built_up": 20.0,
                "cropland": 20.0,
                "vegetation": 20.0,
                "bare": 20.0,
                "water": 20.0,
            }

        # 5. Complete Failure Fallback
        if (sentinel_image is None and sentinel_failed) and osm_failed:
            return SatelliteConfirmationResponse(
                latitude=request.latitude,
                longitude=request.longitude,
                timestamp=request.timestamp,
                predicted_class=request.predicted_class,  # Preserved unchanged
                classification_confidence=request.classification_confidence,  # Preserved unchanged
                image_url=None,
                acquisition_date=None,
                cloud_coverage=None,
                nearby_facilities=[],
                landcover_summary=dict(landcover_distribution),
                confirmation=ConfirmationStatusEnum.UNCERTAIN,
                confirmation_score=50.0,
                reasons=[
                    "All external satellite and geographic data sources (Sentinel-2 and OpenStreetMap) were unreachable",
                    "Confirmation verdict is UNCERTAIN due to missing upstream context",
                ],
                evidence={"external_services_failed": True},
                analysis_timestamp=datetime.now(timezone.utc),
            )

        # 6. Pass evidence to deterministic confirmation engine
        satellite_available = (sentinel_image is not None)
        cloud_quality = sentinel_image.cloud_coverage if sentinel_image else None

        status, score, reasons, evidence = self.confirmation_engine.evaluate_confirmation(
            predicted_class=request.predicted_class,
            classification_confidence=request.classification_confidence,
            nearby_osm_features=nearby_facilities,
            landcover_percentages=landcover_distribution,
            satellite_image_available=satellite_available,
            cloud_quality=cloud_quality,
        )

        if osm_failed:
            reasons.append("OpenStreetMap query failed or timed out; facility context was unavailable")

        # 7. Return structured response
        return SatelliteConfirmationResponse(
            latitude=request.latitude,
            longitude=request.longitude,
            timestamp=request.timestamp,
            predicted_class=request.predicted_class,  # Preserved unchanged
            classification_confidence=request.classification_confidence,  # Preserved unchanged
            image_url=sentinel_image.image_url if sentinel_image else None,
            acquisition_date=sentinel_image.acquisition_date if sentinel_image else None,
            cloud_coverage=sentinel_image.cloud_coverage if sentinel_image else None,
            nearby_facilities=nearby_facilities,
            landcover_summary=dict(landcover_distribution),
            confirmation=status,
            confirmation_score=score,
            reasons=reasons,
            evidence=evidence,
            analysis_timestamp=datetime.now(timezone.utc),
        )
