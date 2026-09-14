"""
Unit and integration tests for Steps 13 & 14:
- SatelliteConfirmationService.confirm_hotspot()
- POST /api/satellite/confirm FastAPI endpoint
- Graceful degradation under partial and total upstream failures
"""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.satellite.osm_client import OSMClient
from backend.satellite.schemas import (
    ConfirmationStatusEnum,
    OSMContextSchema,
    SatelliteConfirmationRequest,
    SatelliteConfirmationResponse,
    SentinelImageInfoSchema,
)
from backend.satellite.sentinel_client import SentinelClient
from backend.satellite.service import SatelliteConfirmationService


class TestConfirmService(unittest.IsolatedAsyncioTestCase):
    """Test suite for confirm_hotspot pipeline in service.py."""

    async def asyncSetUp(self):
        self.mock_sentinel = AsyncMock(spec=SentinelClient)
        self.mock_osm = AsyncMock(spec=OSMClient)
        self.service = SatelliteConfirmationService(
            sentinel_client=self.mock_sentinel,
            osm_client=self.mock_osm,
        )

        # Standard test image
        self.test_image = SentinelImageInfoSchema(
            image_url="s3://copernicus-tiles/sentinel-2/test.tif",
            acquisition_date=datetime.fromisoformat("2026-09-13T10:00:00+00:00"),
            cloud_coverage=12.5,
            bands_available=["B02", "B03", "B04"],
            resolution_m=10,
        )

        # Standard test OSM context
        self.test_osm = OSMContextSchema(
            nearby_facilities=[{"name": "Steel Mill", "type": "industrial", "distance_m": 220}],
            land_use_categories=["industrial"],
            distance_to_nearest_facility_m=220,
        )

    async def test_full_pipeline_industrial_fire_consistent(self):
        """End-to-end confirmation pipeline: Industrial Fire + Facility -> CONSISTENT."""
        self.mock_sentinel.get_latest_image.return_value = self.test_image
        self.mock_sentinel.get_spectral_indices.return_value = {"NDVI": 0.15, "NDBI": 0.45}
        self.mock_osm.get_full_osm_context.return_value = self.test_osm

        request = SatelliteConfirmationRequest(
            latitude=28.6139,
            longitude=77.2090,
            timestamp=datetime.fromisoformat("2026-09-13T14:30:00+00:00"),
            predicted_class="Industrial Fire",
            classification_confidence=0.87,
        )

        response = await self.service.confirm_hotspot(request)

        self.assertIsInstance(response, SatelliteConfirmationResponse)
        # Original classification preserved unchanged
        self.assertEqual(response.predicted_class, "Industrial Fire")
        self.assertEqual(response.classification_confidence, 0.87)
        self.assertEqual(response.confirmation, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(response.confirmation_score, 65.0)
        self.assertIsNotNone(response.image_url)
        self.assertEqual(len(response.nearby_facilities), 1)
        self.assertIsInstance(response.reasons, list)
        self.assertGreater(len(response.reasons), 0)

    async def test_partial_failure_sentinel_unavailable(self):
        """Graceful degradation: Sentinel fails, OSM succeeds -> confirmation continues."""
        # Sentinel raises an exception (e.g. timeout / network error)
        self.mock_sentinel.get_latest_image.side_effect = Exception("Sentinel Hub API timed out")
        self.mock_sentinel.get_spectral_indices.side_effect = Exception("Service unavailable")
        self.mock_osm.get_full_osm_context.return_value = self.test_osm

        request = SatelliteConfirmationRequest(
            latitude=28.6139,
            longitude=77.2090,
            timestamp=datetime.fromisoformat("2026-09-13T14:30:00+00:00"),
            predicted_class="Industrial Fire",
            classification_confidence=0.85,
        )

        # Must not raise exception
        response = await self.service.confirm_hotspot(request)

        self.assertIsInstance(response, SatelliteConfirmationResponse)
        self.assertIsNone(response.image_url)
        # Still confirmed from OSM context
        self.assertEqual(response.confirmation, ConfirmationStatusEnum.CONSISTENT)
        reasons_text = " ".join(response.reasons)
        self.assertIn("unavailable", reasons_text.lower())

    async def test_partial_failure_osm_unavailable(self):
        """Graceful degradation: OSM fails, Sentinel succeeds -> confirmation continues."""
        self.mock_sentinel.get_latest_image.return_value = self.test_image
        self.mock_sentinel.get_spectral_indices.return_value = {"NDVI": 0.65, "NDBI": -0.15}
        self.mock_osm.get_full_osm_context.side_effect = Exception("Overpass 504 Gateway Timeout")

        request = SatelliteConfirmationRequest(
            latitude=30.0000,
            longitude=78.0000,
            timestamp=datetime.fromisoformat("2026-09-13T14:30:00+00:00"),
            predicted_class="Wildfire",
            classification_confidence=0.90,
        )

        response = await self.service.confirm_hotspot(request)

        self.assertIsInstance(response, SatelliteConfirmationResponse)
        self.assertEqual(response.confirmation, ConfirmationStatusEnum.CONSISTENT)
        reasons_text = " ".join(response.reasons)
        self.assertIn("openstreetmap", reasons_text.lower())

    async def test_total_upstream_failure_returns_uncertain(self):
        """Graceful degradation: Both Sentinel and OSM fail -> returns UNCERTAIN without crashing."""
        self.mock_sentinel.get_latest_image.side_effect = Exception("Sentinel down")
        self.mock_sentinel.get_spectral_indices.side_effect = Exception("Sentinel down")
        self.mock_osm.get_full_osm_context.side_effect = Exception("Overpass down")

        request = SatelliteConfirmationRequest(
            latitude=28.6139,
            longitude=77.2090,
            timestamp=datetime.fromisoformat("2026-09-13T14:30:00+00:00"),
            predicted_class="Industrial Fire",
            classification_confidence=0.80,
        )

        response = await self.service.confirm_hotspot(request)

        self.assertIsInstance(response, SatelliteConfirmationResponse)
        self.assertEqual(response.confirmation, ConfirmationStatusEnum.UNCERTAIN)
        self.assertEqual(response.confirmation_score, 50.0)
        reasons_text = " ".join(response.reasons)
        self.assertIn("unreachable", reasons_text.lower())


class TestConfirmEndpoint(unittest.TestCase):
    """Test suite for FastAPI POST /api/satellite/confirm endpoint."""

    def setUp(self):
        self.client = TestClient(app)

    @patch("backend.routes.satellite.get_service")
    def test_confirm_endpoint_success(self, mock_get_service):
        """POST /api/satellite/confirm returns 200 with valid schema."""
        mock_svc = MagicMock()
        mock_svc.confirm_hotspot = AsyncMock(return_value=SatelliteConfirmationResponse(
            latitude=28.6139,
            longitude=77.2090,
            timestamp=datetime.fromisoformat("2026-09-13T14:30:00+00:00"),
            predicted_class="Industrial Fire",
            classification_confidence=0.87,
            image_url="s3://copernicus-tiles/sentinel-2/test.tif",
            acquisition_date=datetime.fromisoformat("2026-09-13T10:00:00+00:00"),
            cloud_coverage=12.5,
            nearby_facilities=[{"name": "Refinery", "type": "industrial", "distance_m": 240}],
            landcover_summary={"built_up": 74.0, "cropland": 4.0, "vegetation": 8.0, "bare": 14.0},
            confirmation=ConfirmationStatusEnum.CONSISTENT,
            confirmation_score=90.0,
            reasons=["Industrial facility located 240m from hotspot"],
            evidence={"has_industrial_facility": True},
            analysis_timestamp=datetime.fromisoformat("2026-09-13T22:30:00+00:00"),
        ))
        mock_get_service.return_value = mock_svc

        payload = {
            "latitude": 28.6139,
            "longitude": 77.2090,
            "timestamp": "2026-09-13T14:30:00Z",
            "predicted_class": "Industrial Fire",
            "classification_confidence": 0.87,
        }

        response = self.client.post("/api/satellite/confirm", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["predicted_class"], "Industrial Fire")
        self.assertEqual(data["classification_confidence"], 0.87)
        self.assertIn(data["confirmation"], ["CONSISTENT", "INCONSISTENT", "UNCERTAIN"])
        self.assertIn("confirmation_score", data)
        self.assertIn("reasons", data)
        self.assertIsInstance(data["reasons"], list)
        self.assertIn("evidence", data)
        self.assertIn("analysis_timestamp", data)

    def test_confirm_endpoint_invalid_coordinates(self):
        """POST /api/satellite/confirm validates latitude boundary (-90 to 90)."""
        payload = {
            "latitude": 125.0,  # Invalid
            "longitude": 77.2090,
            "timestamp": "2026-09-13T14:30:00Z",
            "predicted_class": "Industrial Fire",
            "classification_confidence": 0.87,
        }

        response = self.client.post("/api/satellite/confirm", json=payload)
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
