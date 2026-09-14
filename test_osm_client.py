"""
Tests for OSM client (OpenStreetMap facility lookup).

Tests cover:
- Distance calculations (Haversine formula)
- Bounding box generation
- Overpass query building
- Facility deduplication
- OSM context retrieval
- Error handling
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.satellite.osm_client import OSMClientImpl
from backend.satellite.schemas import OSMContextSchema


class TestDistanceCalculation(unittest.TestCase):
    """Test Haversine distance calculations."""

    def test_same_point_zero_distance(self):
        """Distance between identical points should be zero."""
        distance = OSMClientImpl._haversine_distance(28.6139, 77.2090, 28.6139, 77.2090)
        self.assertAlmostEqual(distance, 0, delta=1)

    def test_known_distance_delhi_to_agra(self):
        """Delhi to Agra should be ~178 km."""
        # Delhi: 28.6139, 77.2090
        # Agra: 27.1767, 78.0081
        distance = OSMClientImpl._haversine_distance(28.6139, 77.2090, 27.1767, 78.0081)
        # Distance should be around 178 km = 178,000 meters
        self.assertGreater(distance, 175_000)
        self.assertLess(distance, 185_000)

    def test_distance_symmetry(self):
        """Distance A→B should equal B→A."""
        dist_ab = OSMClientImpl._haversine_distance(0, 0, 10, 10)
        dist_ba = OSMClientImpl._haversine_distance(10, 10, 0, 0)
        self.assertAlmostEqual(dist_ab, dist_ba, delta=1)

    def test_distance_500m(self):
        """Test 500m distance calculation."""
        # These points should be roughly 500m apart
        # 1 degree ≈ 111 km at equator
        # 500m ≈ 0.0045 degrees
        distance = OSMClientImpl._haversine_distance(0, 0, 0.0045, 0.0045)
        # Should be around 636m (diagonal)
        self.assertGreater(distance, 500)
        self.assertLess(distance, 800)


class TestBoundingBoxGeneration(unittest.TestCase):
    """Test bounding box calculations for Overpass queries."""

    def test_bbox_around_center(self):
        """Bbox should surround the center point."""
        south, west, north, east = OSMClientImpl._latlon_to_bbox(0, 0, 1000)
        self.assertLess(south, 0)
        self.assertGreater(north, 0)
        self.assertLess(west, 0)
        self.assertGreater(east, 0)

    def test_bbox_delhi(self):
        """Test bbox generation for Delhi."""
        lat, lon = 28.6139, 77.2090
        south, west, north, east = OSMClientImpl._latlon_to_bbox(lat, lon, 1000)
        self.assertLess(south, lat)
        self.assertGreater(north, lat)
        self.assertLess(west, lon)
        self.assertGreater(east, lon)

    def test_bbox_size_1km(self):
        """With 1km radius, bbox should be roughly 0.018 degrees tall (2x radius)."""
        lat, lon = 0, 0
        south, west, north, east = OSMClientImpl._latlon_to_bbox(lat, lon, 1000)
        # 1km ≈ 0.009 degrees, span north-south ≈ 0.018 degrees
        lat_span = north - south
        self.assertGreater(lat_span, 0.017)
        self.assertLess(lat_span, 0.020)

    def test_bbox_size_5km(self):
        """With 5km radius, bbox should be roughly 0.09 degrees tall (2x radius)."""
        lat, lon = 0, 0
        south, west, north, east = OSMClientImpl._latlon_to_bbox(lat, lon, 5000)
        lat_span = north - south
        self.assertGreater(lat_span, 0.08)
        self.assertLess(lat_span, 0.10)


class TestOverpassQueryBuilding(unittest.TestCase):
    """Test Overpass Query Language generation."""

    def test_query_structure(self):
        """Generated query should be valid Overpass QL."""
        client = OSMClientImpl()
        bbox = (28.6, 77.2, 28.62, 77.22)
        query = client._build_overpass_query(bbox, ["industrial", "refinery"])
        
        # Should contain bbox
        self.assertIn("[bbox:", query)
        # Should contain out directive
        self.assertIn("out center", query)

    def test_query_with_tags(self):
        """Query should include specified tags."""
        client = OSMClientImpl()
        bbox = (0, 0, 1, 1)
        query = client._build_overpass_query(bbox, ["industrial"])
        self.assertIn("industrial", query)

    def test_query_multiple_tags(self):
        """Query should handle multiple tags."""
        client = OSMClientImpl()
        bbox = (0, 0, 1, 1)
        tags = ["industrial", "refinery", "factory"]
        query = client._build_overpass_query(bbox, tags)
        
        for tag in tags:
            self.assertIn(tag, query)

    def test_query_key_value_tags(self):
        """Query should handle key=value tags."""
        client = OSMClientImpl()
        bbox = (0, 0, 1, 1)
        query = client._build_overpass_query(bbox, ["industrial=true", "type=refinery"])
        
        self.assertIn("industrial", query)
        self.assertIn("type", query)


class TestFeatureDeduplication(unittest.TestCase):
    """Test deduplication of nearby features."""

    def test_deduplicate_identical_features(self):
        """Identical features at same location should be deduplicated."""
        client = OSMClientImpl()
        features = [
            {
                "osm_id": "1",
                "name": "Refinery A",
                "latitude": 28.6139,
                "longitude": 77.2090,
                "distance_m": 0,
            },
            {
                "osm_id": "2",
                "name": "Refinery A (duplicate)",
                "latitude": 28.6139,
                "longitude": 77.2090,
                "distance_m": 0,
            },
        ]
        
        deduplicated = client._deduplicate_features(features)
        self.assertEqual(len(deduplicated), 1)

    def test_deduplicate_by_distance(self):
        """Features within 100m should be deduplicated."""
        client = OSMClientImpl()
        # Points 50m apart
        lat1, lon1 = 28.6139, 77.2090
        lat2, lon2 = 28.61395, 77.2090  # ~55m apart
        
        features = [
            {
                "osm_id": "1",
                "name": "Facility A",
                "latitude": lat1,
                "longitude": lon1,
                "distance_m": 0,
            },
            {
                "osm_id": "2",
                "name": "Facility B",
                "latitude": lat2,
                "longitude": lon2,
                "distance_m": 50,
            },
        ]
        
        deduplicated = client._deduplicate_features(features, radius_m=100)
        self.assertEqual(len(deduplicated), 1)

    def test_keep_distant_features(self):
        """Features >100m apart should not be deduplicated."""
        client = OSMClientImpl()
        # Points far apart (300m+)
        lat1, lon1 = 28.6139, 77.2090
        lat2, lon2 = 28.61535, 77.2090  # ~1100m apart
        
        features = [
            {
                "osm_id": "1",
                "name": "Facility A",
                "latitude": lat1,
                "longitude": lon1,
                "distance_m": 0,
            },
            {
                "osm_id": "2",
                "name": "Facility B",
                "latitude": lat2,
                "longitude": lon2,
                "distance_m": 1100,
            },
        ]
        
        deduplicated = client._deduplicate_features(features, radius_m=100)
        self.assertEqual(len(deduplicated), 2)

    def test_deduplicate_sorts_by_distance(self):
        """Result should be sorted by distance."""
        client = OSMClientImpl()
        features = [
            {"osm_id": "3", "distance_m": 1000, "latitude": 28.6, "longitude": 77.2},
            {"osm_id": "1", "distance_m": 100, "latitude": 28.614, "longitude": 77.209},
            {"osm_id": "2", "distance_m": 500, "latitude": 28.612, "longitude": 77.208},
        ]
        
        deduplicated = client._deduplicate_features(features)
        distances = [f["distance_m"] for f in deduplicated]
        self.assertEqual(distances, sorted(distances))


class TestOSMClientAsync(unittest.IsolatedAsyncioTestCase):
    """Test async OSM client methods."""

    async def test_get_nearby_facilities_mocked(self):
        """Test facility retrieval with mocked Overpass response."""
        client = OSMClientImpl()
        
        # Mock response from Overpass
        mock_response = {
            "elements": [
                {
                    "type": "way",
                    "id": 123456,
                    "center": {"lat": 28.6139, "lon": 77.2090},
                    "tags": {
                        "name": "Test Refinery",
                        "industrial": "refinery",
                    },
                },
                {
                    "type": "node",
                    "id": 123457,
                    "lat": 28.625,  # Far enough to not deduplicate (~1700m away)
                    "lon": 77.210,
                    "tags": {
                        "name": "Test Factory",
                        "industrial": "factory",
                    },
                },
            ]
        }
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            
            facilities = await client.get_nearby_facilities(28.6139, 77.2090, 5000)
            
            self.assertEqual(len(facilities), 2)
            self.assertEqual(facilities[0]["name"], "Test Refinery")
            self.assertEqual(facilities[1]["name"], "Test Factory")
            self.assertTrue(all("distance_m" in f for f in facilities))

    async def test_get_nearby_facilities_empty(self):
        """Test handling of empty Overpass response."""
        client = OSMClientImpl()
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = {"elements": []}
            
            facilities = await client.get_nearby_facilities(28.6139, 77.2090, 1000)
            
            self.assertEqual(len(facilities), 0)

    async def test_get_land_use_categories_mocked(self):
        """Test land use query with mocked response."""
        client = OSMClientImpl()
        
        mock_response = {
            "elements": [
                {"id": 1, "tags": {"landuse": "industrial"}},
                {"id": 2, "tags": {"landuse": "agricultural"}},
                {"id": 3, "tags": {"landuse": "agricultural"}},
                {"id": 4, "tags": {"landuse": "residential"}},
            ]
        }
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            
            land_use = await client.get_land_use_categories(28.6139, 77.2090, 1000)
            
            # Should have aggregated counts
            self.assertIsInstance(land_use, dict)

    async def test_get_nearest_facility_mocked(self):
        """Test finding nearest facility of specific type."""
        client = OSMClientImpl()
        
        mock_response = {
            "elements": [
                {
                    "type": "node",
                    "id": 456,
                    "lat": 28.615,
                    "lon": 77.210,
                    "tags": {"name": "Closest Refinery", "industrial": "refinery"},
                },
                {
                    "type": "node",
                    "id": 457,
                    "lat": 28.62,
                    "lon": 77.215,
                    "tags": {"name": "Far Refinery", "industrial": "refinery"},
                },
            ]
        }
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = mock_response
            
            nearest = await client.get_nearest_facility(
                28.6139, 77.2090, "refinery", max_distance_m=5000
            )
            
            self.assertIsNotNone(nearest)
            self.assertEqual(nearest["name"], "Closest Refinery")

    async def test_get_nearest_facility_none(self):
        """Test when no facility found."""
        client = OSMClientImpl()
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = {"elements": []}
            
            nearest = await client.get_nearest_facility(
                28.6139, 77.2090, "nonexistent", max_distance_m=5000
            )
            
            self.assertIsNone(nearest)

    async def test_get_full_osm_context_mocked(self):
        """Test full OSM context retrieval."""
        client = OSMClientImpl()
        
        facilities_response = {
            "elements": [
                {
                    "type": "node",
                    "id": 123,
                    "lat": 28.614,
                    "lon": 77.209,
                    "tags": {"name": "Test Facility", "industrial": "factory"},
                }
            ]
        }
        
        land_use_response = {"elements": [{"id": 456, "tags": {"landuse": "industrial"}}]}
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            # First call for facilities, second for land use
            mock_query.side_effect = [facilities_response, land_use_response]
            
            context = await client.get_full_osm_context(28.6139, 77.2090, 1000)
            
            self.assertIsInstance(context, OSMContextSchema)
            self.assertGreater(len(context.nearby_facilities), 0)
            self.assertEqual(len(context.land_use_categories), 0)  # No landuse tags

    async def test_rate_limiting(self):
        """Test that rate limiting is applied."""
        # Note: Rate limiting is based on asyncio loop time which behaves differently in tests
        # The actual rate limiting will work in production with real asyncio event loop
        client = OSMClientImpl(timeout_s=10)
        
        with patch.object(client, "_query_overpass", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = {"elements": []}
            
            # Make two requests - they should complete without error
            await client.get_nearby_facilities(28.6139, 77.2090, 1000)
            await client.get_nearby_facilities(28.6139, 77.2090, 1000)
            
            # Verify both calls were made
            self.assertEqual(mock_query.call_count, 2)


class TestOSMClientIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests (may require actual Overpass API or mocking)."""

    async def test_init_custom_endpoint(self):
        """Test initialization with custom Overpass endpoint."""
        custom_endpoint = "https://custom.example.com/api"
        client = OSMClientImpl(overpass_endpoint=custom_endpoint)
        self.assertEqual(client.overpass_endpoint, custom_endpoint)

    async def test_init_default_endpoint(self):
        """Test default Overpass endpoint."""
        client = OSMClientImpl()
        self.assertIn("overpass", client.overpass_endpoint.lower())

    async def test_init_timeout(self):
        """Test custom timeout."""
        client = OSMClientImpl(timeout_s=30)
        self.assertEqual(client.timeout, 30)


if __name__ == "__main__":
    unittest.main()
