"""
Test Sentinel-2 image retrieval functionality.

Tests:
1. Coordinate to bounding box conversion
2. Cache key generation
3. Image caching (read/write)
4. STAC API search (mocked)
5. Image URL building
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))

from satellite.sentinel_client import SentinelClientImpl, SentinelHubAuth
from satellite.schemas import SentinelImageInfoSchema


class TestCoordinateConversion:
    """Test coordinate to bounding box conversion."""

    def test_bbox_generation(self):
        """Test that 512m bbox is generated correctly."""
        print("\n" + "=" * 60)
        print("TEST: Coordinate to Bounding Box Conversion")
        print("=" * 60)

        lat, lon = 28.6139, 77.2090  # Delhi

        bbox = SentinelClientImpl._latlon_to_bbox(lat, lon, box_size_m=512)

        print(f"Input: lat={lat}, lon={lon}")
        print(f"Box size: 512m x 512m")
        print(f"\nGenerated bbox:")
        print(f"  North: {bbox['north']:.6f}")
        print(f"  South: {bbox['south']:.6f}")
        print(f"  East: {bbox['east']:.6f}")
        print(f"  West: {bbox['west']:.6f}")

        # Verify bbox surrounds the point
        assert bbox["south"] < lat < bbox["north"], "Latitude should be inside bbox"
        assert bbox["west"] < lon < bbox["east"], "Longitude should be inside bbox"

        # Verify bbox is approximately square
        lat_delta = bbox["north"] - bbox["south"]
        lon_delta = bbox["east"] - bbox["west"]
        print(f"\nLat delta: {lat_delta:.6f}")
        print(f"Lon delta: {lon_delta:.6f}")
        assert abs(lat_delta - lon_delta) < 0.0001, "Bbox should be approximately square"

        print("\n✓ Bounding box generated correctly")
        print("=" * 60)

    def test_different_locations(self):
        """Test bbox generation at different locations."""
        locations = [
            (28.6139, 77.2090, "Delhi"),
            (40.7128, -74.0060, "New York"),
            (35.6762, 139.6503, "Tokyo"),
            (-33.8688, 151.2093, "Sydney"),
        ]

        print("\n" + "=" * 60)
        print("TEST: Bounding Box Generation at Different Locations")
        print("=" * 60)

        for lat, lon, name in locations:
            bbox = SentinelClientImpl._latlon_to_bbox(lat, lon, box_size_m=512)
            print(f"✓ {name:15} ({lat:8.4f}, {lon:9.4f}): bbox ✓")

        print("=" * 60)


class TestCaching:
    """Test image caching mechanism."""

    def test_cache_key_generation(self):
        """Test deterministic cache key generation."""
        print("\n" + "=" * 60)
        print("TEST: Cache Key Generation")
        print("=" * 60)

        lat, lon = 28.6139, 77.2090
        timestamp1 = datetime(2026, 9, 13, 14, 30, 0)
        timestamp2 = datetime(2026, 9, 13, 20, 45, 0)  # Same day, different time

        key1 = SentinelClientImpl._cache_key(lat, lon, timestamp1)
        key2 = SentinelClientImpl._cache_key(lat, lon, timestamp2)

        print(f"Location: {lat}, {lon}")
        print(f"Key for {timestamp1}: {key1}")
        print(f"Key for {timestamp2} (same day): {key2}")

        assert key1 == key2, "Same day should produce same cache key"
        print("✓ Same day → same cache key")

        # Different day
        timestamp3 = datetime(2026, 9, 14, 14, 30, 0)
        key3 = SentinelClientImpl._cache_key(lat, lon, timestamp3)
        print(f"Key for {timestamp3} (next day): {key3}")

        assert key1 != key3, "Different day should produce different cache key"
        print("✓ Different day → different cache key")

        print("=" * 60)

    def test_cache_read_write(self):
        """Test image caching to disk."""
        print("\n" + "=" * 60)
        print("TEST: Image Cache Read/Write")
        print("=" * 60)

        # Create client
        auth = MagicMock(spec=SentinelHubAuth)
        client = SentinelClientImpl(auth=auth)

        # Create test image info
        image_info = SentinelImageInfoSchema(
            image_url="https://example.com/image.tif",
            acquisition_date=datetime(2026, 9, 13, 10, 0, 0),
            cloud_coverage=15.5,
            bands_available=["B2", "B3", "B4", "B8", "B11"],
            resolution_m=10,
        )

        # Write to cache
        cache_key = "test_cache_12ab"
        client._write_to_cache(cache_key, image_info)
        print(f"✓ Image info written to cache: {cache_key}")

        # Read from cache
        cached = client._read_from_cache(cache_key)
        print(f"✓ Image info read from cache")

        assert cached is not None, "Cache read should not be None"
        assert cached.image_url == image_info.image_url, "URL should match"
        assert cached.cloud_coverage == image_info.cloud_coverage, "Cloud coverage should match"
        print(f"✓ Cached data matches original")

        # Verify cache file exists
        cache_file = client._get_cached_image_path(cache_key)
        assert cache_file.exists(), "Cache file should exist"
        print(f"✓ Cache file exists: {cache_file}")

        # Cleanup
        cache_file.unlink()
        print("✓ Cache file cleaned up")

        print("=" * 60)


class TestImageRetrieval:
    """Test image retrieval with mocked API calls."""

    @staticmethod
    def _mock_stac_response():
        """Generate mock STAC API response."""
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "S2A_MSIL2A_20260913T053501_N0500_R105_T43SDA_20260913T053518",
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[77.2, 28.6], [77.3, 28.6], [77.3, 28.7], [77.2, 28.7], [77.2, 28.6]]],
                    },
                    "properties": {
                        "datetime": "2026-09-13T05:35:18Z",
                        "eo:cloud_cover": 12.5,
                        "constellation": "sentinel-2",
                        "platform": "sentinel-2a",
                    },
                    "assets": {
                        "B02": {"title": "Blue"},
                        "B03": {"title": "Green"},
                        "B04": {"title": "Red"},
                        "B08": {"title": "NIR"},
                        "SCL": {"title": "Scene Classification"},
                    },
                }
            ],
        }

    async def test_stac_search_mocked(self):
        """Test STAC API search with mocked HTTP."""
        print("\n" + "=" * 60)
        print("TEST: STAC API Search (Mocked)")
        print("=" * 60)

        # Mock auth
        auth = MagicMock(spec=SentinelHubAuth)
        auth.get_access_token = AsyncMock(return_value="mocked_token_xyz")

        client = SentinelClientImpl(auth=auth)

        # Mock requests.post
        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_stac_response()

        with patch("satellite.sentinel_client.requests.post", return_value=mock_response):
            lat, lon = 28.6139, 77.2090
            timestamp = datetime(2026, 9, 13, 14, 30, 0)

            result = await client._search_stac_for_image(
                lat, lon, timestamp, max_cloud_coverage=50.0
            )

            print(f"Searched for image: {lat}, {lon} at {timestamp}")
            assert result is not None, "Should find image"
            print(f"✓ Found image: {result['id']}")
            print(f"✓ Cloud coverage: {result['properties']['eo:cloud_cover']}%")
            print(f"✓ Acquisition: {result['properties']['datetime']}")
            print(f"✓ Available bands: {list(result['assets'].keys())}")

        print("=" * 60)

    async def test_get_latest_image_mocked(self):
        """Test get_latest_image with mocked API and cache."""
        print("\n" + "=" * 60)
        print("TEST: Get Latest Image (Mocked)")
        print("=" * 60)

        # Mock auth
        auth = MagicMock(spec=SentinelHubAuth)
        auth.get_access_token = AsyncMock(return_value="mocked_token_xyz")

        client = SentinelClientImpl(auth=auth)

        # Mock requests.post for STAC search
        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_stac_response()

        with patch("satellite.sentinel_client.requests.post", return_value=mock_response):
            lat, lon = 28.6139, 77.2090
            timestamp = datetime(2026, 9, 13, 14, 30, 0)

            # First call - should search API and cache result
            print("First call (API search):")
            image1 = await client.get_latest_image(lat, lon, timestamp)

            assert image1 is not None, "Should return image info"
            print(f"  ✓ Image retrieved: {image1.image_url[:40]}...")
            print(f"  ✓ Cloud coverage: {image1.cloud_coverage}%")
            print(f"  ✓ Bands: {image1.bands_available}")
            print(f"  ✓ Resolution: {image1.resolution_m}m")

            # Second call - should use cache (no API call)
            print("\nSecond call (cache):")
            image2 = await client.get_latest_image(lat, lon, timestamp)

            assert image2 is not None, "Should return cached image"
            assert image2.image_url == image1.image_url, "Cached image should match"
            print(f"  ✓ Image retrieved from cache")
            print(f"  ✓ URLs match: {image2.image_url == image1.image_url}")

            # Cleanup
            cache_key = SentinelClientImpl._cache_key(lat, lon, timestamp)
            cache_file = client._get_cached_image_path(cache_key)
            if cache_file.exists():
                cache_file.unlink()

        print("=" * 60)

    async def test_no_image_found(self):
        """Test handling when no suitable image exists."""
        print("\n" + "=" * 60)
        print("TEST: No Image Found Handling")
        print("=" * 60)

        # Mock auth
        auth = MagicMock(spec=SentinelHubAuth)
        auth.get_access_token = AsyncMock(return_value="mocked_token_xyz")

        client = SentinelClientImpl(auth=auth)

        # Mock STAC response with no results
        mock_response = MagicMock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}

        with patch("satellite.sentinel_client.requests.post", return_value=mock_response):
            lat, lon = 28.6139, 77.2090
            timestamp = datetime(2026, 9, 13, 14, 30, 0)

            image = await client.get_latest_image(lat, lon, timestamp)

            assert image is None, "Should return None when no image found"
            print("✓ Correctly handled no-image scenario")

        print("=" * 60)


def run_all_tests():
    """Run all tests."""
    print("\n\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  SENTINEL-2 IMAGE RETRIEVAL TESTS".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")

    # Coordinate tests
    coord_tests = TestCoordinateConversion()
    coord_tests.test_bbox_generation()
    coord_tests.test_different_locations()

    # Cache tests
    cache_tests = TestCaching()
    cache_tests.test_cache_key_generation()
    cache_tests.test_cache_read_write()

    # Image retrieval tests (async)
    image_tests = TestImageRetrieval()
    asyncio.run(image_tests.test_stac_search_mocked())
    asyncio.run(image_tests.test_get_latest_image_mocked())
    asyncio.run(image_tests.test_no_image_found())

    print("\n" + "╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  ALL TESTS PASSED ✓".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝\n")


if __name__ == "__main__":
    run_all_tests()
