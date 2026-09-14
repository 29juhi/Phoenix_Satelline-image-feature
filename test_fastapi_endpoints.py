"""
Test FastAPI satellite endpoints.

Tests:
1. Image retrieval endpoint with valid coordinates
2. Input validation (invalid lat/lon/timestamp)
3. Error handling (no image found, API errors)
4. Service status endpoint
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from dotenv import load_dotenv

# Load env vars
load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from fastapi.testclient import TestClient

from main import app
from satellite.schemas import SentinelImageInfoSchema

# Create test client
client = TestClient(app)


class TestSatelliteEndpoints:
    """Test satellite image retrieval endpoints."""

    def test_health_check(self):
        """Test health check endpoint."""
        print("\n" + "=" * 60)
        print("TEST: Health Check Endpoint")
        print("=" * 60)

        response = client.get("/health")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "phoenix"
        print("✓ Health check: OK")
        print("=" * 60)

    def test_service_status(self):
        """Test satellite service status endpoint."""
        print("\n" + "=" * 60)
        print("TEST: Satellite Service Status Endpoint")
        print("=" * 60)

        response = client.get("/api/satellite/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "operational"
        assert data["service"] == "sentinel-2"
        print(f"✓ Service status: {data['status']}")
        print(f"✓ Service: {data['service']}")
        print(f"✓ Cache dir: {data['cache_directory']}")
        print("=" * 60)

    def test_image_retrieval_valid_input(self):
        """Test image retrieval with valid coordinates."""
        print("\n" + "=" * 60)
        print("TEST: Image Retrieval - Valid Input")
        print("=" * 60)

        # Mock the Sentinel client
        mock_image_info = SentinelImageInfoSchema(
            image_url="https://example.com/image.tif",
            acquisition_date=datetime(2026, 9, 13, 10, 0, 0),
            cloud_coverage=15.5,
            bands_available=["B2", "B3", "B4", "B8", "B11"],
            resolution_m=10,
        )

        with patch(
            "routes.satellite.get_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.sentinel.get_latest_image = AsyncMock(
                return_value=mock_image_info
            )
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/satellite/image",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "timestamp": "2026-09-13T14:30:00Z",
                },
            )

        print(f"Response status: {response.status_code}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.json()
        assert data["success"] is True
        assert data["image"] is not None
        assert data["image"]["image_url"] == "https://example.com/image.tif"
        assert data["image"]["cloud_coverage"] == 15.5
        assert data["image"]["bands_available"] == ["B2", "B3", "B4", "B8", "B11"]
        print("✓ Image retrieved successfully")
        print(f"✓ Cloud coverage: {data['image']['cloud_coverage']}%")
        print(f"✓ Bands: {data['image']['bands_available']}")
        print("=" * 60)

    def test_image_retrieval_no_image_found(self):
        """Test image retrieval when no suitable image is found."""
        print("\n" + "=" * 60)
        print("TEST: Image Retrieval - No Image Found")
        print("=" * 60)

        with patch(
            "routes.satellite.get_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.sentinel.get_latest_image = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/satellite/image",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "timestamp": "2026-09-13T14:30:00Z",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["image"] is None
        assert "No suitable" in data["message"]
        print("✓ Correctly returned 'no image found' response")
        print(f"✓ Message: {data['message'][:50]}...")
        print("=" * 60)

    def test_invalid_latitude(self):
        """Test validation of latitude parameter."""
        print("\n" + "=" * 60)
        print("TEST: Input Validation - Invalid Latitude")
        print("=" * 60)

        # Latitude > 90
        response = client.get(
            "/api/satellite/image",
            params={
                "latitude": 95.0,  # Invalid
                "longitude": 77.2090,
                "timestamp": "2026-09-13T14:30:00Z",
            },
        )

        assert response.status_code == 422
        data = response.json()
        detail = data.get("detail")
        if isinstance(detail, list):
            # FastAPI validation errors come as list
            detail_str = str(detail)
        else:
            detail_str = str(detail)
        
        assert "latitude" in detail_str.lower() or "95" in detail_str
        print(f"✓ Rejected invalid latitude: {response.status_code}")
        print(f"✓ Error: {detail_str[:60]}...")
        print("=" * 60)

    def test_invalid_longitude(self):
        """Test validation of longitude parameter."""
        print("\n" + "=" * 60)
        print("TEST: Input Validation - Invalid Longitude")
        print("=" * 60)

        # Longitude > 180
        response = client.get(
            "/api/satellite/image",
            params={
                "latitude": 28.6139,
                "longitude": 185.0,  # Invalid
                "timestamp": "2026-09-13T14:30:00Z",
            },
        )

        assert response.status_code == 422
        data = response.json()
        detail = data.get("detail")
        if isinstance(detail, list):
            detail_str = str(detail)
        else:
            detail_str = str(detail)
        
        assert "longitude" in detail_str.lower() or "185" in detail_str
        print(f"✓ Rejected invalid longitude: {response.status_code}")
        print(f"✓ Error: {detail_str[:60]}...")
        print("=" * 60)

    def test_invalid_timestamp(self):
        """Test validation of timestamp parameter."""
        print("\n" + "=" * 60)
        print("TEST: Input Validation - Invalid Timestamp")
        print("=" * 60)

        # Invalid ISO format
        response = client.get(
            "/api/satellite/image",
            params={
                "latitude": 28.6139,
                "longitude": 77.2090,
                "timestamp": "not-a-valid-date",  # Invalid
            },
        )

        assert response.status_code == 422
        data = response.json()
        detail = data.get("detail")
        if isinstance(detail, list):
            detail_str = str(detail)
        else:
            detail_str = str(detail)
        
        assert "timestamp" in detail_str.lower() or "datetime" in detail_str.lower()
        print(f"✓ Rejected invalid timestamp: {response.status_code}")
        print(f"✓ Error: {detail_str[:60]}...")
        print("=" * 60)

    def test_missing_required_parameter(self):
        """Test that missing required parameters are caught."""
        print("\n" + "=" * 60)
        print("TEST: Input Validation - Missing Required Parameter")
        print("=" * 60)

        # Missing latitude
        response = client.get(
            "/api/satellite/image",
            params={
                "longitude": 77.2090,
                "timestamp": "2026-09-13T14:30:00Z",
            },
        )

        assert response.status_code == 422
        print(f"✓ Rejected missing parameter: {response.status_code}")
        print("=" * 60)

    def test_api_error_handling(self):
        """Test error handling for API failures."""
        print("\n" + "=" * 60)
        print("TEST: API Error Handling")
        print("=" * 60)

        with patch(
            "routes.satellite.get_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.sentinel.get_latest_image = AsyncMock(
                side_effect=Exception("404 Image not found")
            )
            mock_get_service.return_value = mock_service

            response = client.get(
                "/api/satellite/image",
                params={
                    "latitude": 28.6139,
                    "longitude": 77.2090,
                    "timestamp": "2026-09-13T14:30:00Z",
                },
            )

        assert response.status_code == 404
        data = response.json()
        assert "No suitable imagery" in data["detail"]
        print(f"✓ Handled 404 error: {response.status_code}")
        print(f"✓ Message: {data['detail'][:50]}...")
        print("=" * 60)

    def test_multiple_locations(self):
        """Test retrieval at different locations."""
        print("\n" + "=" * 60)
        print("TEST: Multiple Locations")
        print("=" * 60)

        locations = [
            (28.6139, 77.2090, "Delhi"),
            (40.7128, -74.0060, "New York"),
            (35.6762, 139.6503, "Tokyo"),
            (-33.8688, 151.2093, "Sydney"),
        ]

        mock_image_info = SentinelImageInfoSchema(
            image_url="https://example.com/image.tif",
            acquisition_date=datetime(2026, 9, 13, 10, 0, 0),
            cloud_coverage=12.5,
            bands_available=["B2", "B3", "B4"],
            resolution_m=10,
        )

        for lat, lon, name in locations:
            with patch(
                "routes.satellite.get_service"
            ) as mock_get_service:
                mock_service = MagicMock()
                mock_service.sentinel.get_latest_image = AsyncMock(
                    return_value=mock_image_info
                )
                mock_get_service.return_value = mock_service

                response = client.get(
                    "/api/satellite/image",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "timestamp": "2026-09-13T14:30:00Z",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                print(f"✓ {name:15} ({lat:8.4f}, {lon:9.4f}): Image retrieved")

        print("=" * 60)


def run_all_tests():
    """Run all endpoint tests."""
    print("\n\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  FASTAPI SATELLITE ENDPOINTS TESTS".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")

    tests = TestSatelliteEndpoints()

    tests.test_health_check()
    tests.test_service_status()
    tests.test_image_retrieval_valid_input()
    tests.test_image_retrieval_no_image_found()
    tests.test_invalid_latitude()
    tests.test_invalid_longitude()
    tests.test_invalid_timestamp()
    tests.test_missing_required_parameter()
    tests.test_api_error_handling()
    tests.test_multiple_locations()

    print("\n" + "╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  ALL ENDPOINT TESTS PASSED ✓".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝\n")


if __name__ == "__main__":
    run_all_tests()
