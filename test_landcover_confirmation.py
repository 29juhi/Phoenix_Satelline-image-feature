"""
Tests for land cover analysis and confirmation rules engine.

Tests cover:
- Land cover classification
- Percentage distribution calculations
- Built-up area calculation
- Industrial fire confirmation rules
- Cropland fire confirmation rules
- Forest fire confirmation rules
"""

import unittest
from unittest.mock import AsyncMock, patch

from backend.satellite.confirmation import ConfirmationRulesEngine
from backend.satellite.landcover import LandCoverAnalyzer
from backend.satellite.schemas import (
    ConfirmationStatusEnum,
    LandCoverContextSchema,
    LandCoverTypeEnum,
    OSMContextSchema,
    PredictedClassEnum,
)


class TestLandCoverClassification(unittest.IsolatedAsyncioTestCase):
    """Test land cover type classification."""

    async def test_classify_industrial_from_facilities(self):
        """Industrial facility should classify as INDUSTRIAL."""
        analyzer = LandCoverAnalyzer()
        
        facilities = [
            {"name": "Refinery", "type": "refinery", "distance_m": 100}
        ]
        
        result = await analyzer.classify_landcover(
            28.6, 77.2,
            sentinel_indices=None,
            osm_facilities=facilities,
            osm_land_use={}
        )
        
        self.assertEqual(result, LandCoverTypeEnum.INDUSTRIAL)

    async def test_classify_industrial_from_ndbi(self):
        """High NDBI should classify as URBAN/INDUSTRIAL."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDBI": 0.4}  # Above dense_urban threshold
        
        result = await analyzer.classify_landcover(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertEqual(result, LandCoverTypeEnum.URBAN)

    async def test_classify_cropland_from_agriculture(self):
        """Agricultural land use should classify as CROPLAND."""
        analyzer = LandCoverAnalyzer()
        
        land_use = {"agricultural": 2, "farmland": 1}
        
        result = await analyzer.classify_landcover(
            28.6, 77.2,
            sentinel_indices=None,
            osm_facilities=[],
            osm_land_use=land_use
        )
        
        self.assertEqual(result, LandCoverTypeEnum.CROPLAND)

    async def test_classify_forest_from_ndvi(self):
        """High NDVI should classify as FOREST."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDVI": 0.7}  # Above dense_vegetation
        
        result = await analyzer.classify_landcover(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertEqual(result, LandCoverTypeEnum.FOREST)

    async def test_classify_water(self):
        """Low NDMI should classify as WATER."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDMI": -0.5}  # Below water threshold
        
        result = await analyzer.classify_landcover(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertEqual(result, LandCoverTypeEnum.WATER)

    async def test_classify_barren(self):
        """Low NDVI should classify as BARREN."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDVI": -0.1}  # Low vegetation
        
        result = await analyzer.classify_landcover(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertEqual(result, LandCoverTypeEnum.BARREN)


class TestLandCoverDistribution(unittest.IsolatedAsyncioTestCase):
    """Test land cover percentage distribution."""

    async def test_distribution_high_ndvi(self):
        """High NDVI should result in high vegetation percentage."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDVI": 0.7, "NDBI": -0.1}  # Dense vegetation, no build-up
        
        dist = await analyzer.get_landcover_distribution(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertGreater(dist.get("vegetation", 0), 50)
        self.assertEqual(sum(dist.values()), 100.0)  # Should sum to 100

    async def test_distribution_high_ndbi(self):
        """High NDBI should result in high industrial percentage."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDVI": 0.1, "NDBI": 0.5}  # Dense built-up
        
        dist = await analyzer.get_landcover_distribution(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertGreater(dist.get("industrial", 0), 50)

    async def test_distribution_sums_to_100(self):
        """Distribution percentages should always sum to 100."""
        analyzer = LandCoverAnalyzer()
        
        indices = {"NDVI": 0.4, "NDBI": 0.2, "NDMI": 0.1}
        
        dist = await analyzer.get_landcover_distribution(
            28.6, 77.2,
            sentinel_indices=indices,
            osm_facilities=[],
            osm_land_use={}
        )
        
        self.assertAlmostEqual(sum(dist.values()), 100.0, places=1)


class TestBuiltUpCalculation(unittest.IsolatedAsyncioTestCase):
    """Test built-up area percentage calculation."""

    async def test_buildup_from_osm_only(self):
        """Built-up should be calculated from OSM land use."""
        analyzer = LandCoverAnalyzer()
        
        land_use = {"industrial": 2, "residential": 2, "commercial": 1}
        
        buildup = await analyzer.calculate_built_up_percentage(land_use, None)
        
        self.assertGreater(buildup, 20)
        self.assertLessEqual(buildup, 100)

    async def test_buildup_combined_osm_sentinel(self):
        """Built-up should combine OSM and Sentinel data."""
        analyzer = LandCoverAnalyzer()
        
        land_use = {"industrial": 2}
        sentinel_mask = {"built_up_percentage": 40}
        
        buildup = await analyzer.calculate_built_up_percentage(land_use, sentinel_mask)
        
        # Should include contributions from both sources
        self.assertGreater(buildup, 20)

    async def test_buildup_zero_without_data(self):
        """Built-up should be 0 without OSM or Sentinel data."""
        analyzer = LandCoverAnalyzer()
        
        buildup = await analyzer.calculate_built_up_percentage({}, None)
        
        self.assertEqual(buildup, 0.0)


class TestIndustrialFireConfirmation(unittest.IsolatedAsyncioTestCase):
    """Test industrial fire confirmation rules."""

    async def test_industrial_fire_consistent_with_facility(self):
        """Industrial fire should be CONSISTENT with nearby industrial facility."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[{"name": "Refinery", "type": "refinery", "distance_m": 243}],
            land_use_categories=["industrial"],
            distance_to_nearest_facility_m=243,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.INDUSTRIAL,
            land_cover_distribution={"industrial": 65, "urban": 20, "vegetation": 15},
            ndvi_value=0.2,
            built_up_percentage=75.0,
        )
        
        status, confidence, reasons = await engine.evaluate_industrial_fire(
            0.85, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreater(confidence, 0.6)
        self.assertGreater(len(reasons), 0)

    async def test_industrial_fire_inconsistent_with_forest(self):
        """Industrial fire should be INCONSISTENT with forest land cover."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["forest"],
            distance_to_nearest_facility_m=5000,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.FOREST,
            land_cover_distribution={"vegetation": 80, "bare": 20},
            ndvi_value=0.7,
            built_up_percentage=5.0,
        )
        
        status, confidence, reasons = await engine.evaluate_industrial_fire(
            0.85, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)
        self.assertGreater(len(reasons), 0)

    async def test_industrial_fire_uncertain_without_clear_evidence(self):
        """Industrial fire should be UNCERTAIN with mixed evidence."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["grassland"],
            distance_to_nearest_facility_m=None,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.GRASSLAND,
            land_cover_distribution={"vegetation": 40, "bare": 60},
            ndvi_value=0.25,
            built_up_percentage=15.0,
        )
        
        status, confidence, reasons = await engine.evaluate_industrial_fire(
            0.85, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.UNCERTAIN)


class TestCroplandFireConfirmation(unittest.IsolatedAsyncioTestCase):
    """Test cropland fire confirmation rules."""

    async def test_cropland_fire_consistent(self):
        """Cropland fire should be CONSISTENT with cropland environment."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["agricultural", "farmland"],
            distance_to_nearest_facility_m=None,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.CROPLAND,
            land_cover_distribution={"cropland": 60, "vegetation": 30, "bare": 10},
            ndvi_value=0.5,
            built_up_percentage=5.0,
        )
        
        status, confidence, reasons = await engine.evaluate_cropland_fire(
            0.80, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreater(confidence, 0.5)

    async def test_cropland_fire_inconsistent_with_industrial(self):
        """Cropland fire should be INCONSISTENT with industrial environment."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[{"type": "refinery"}],
            land_use_categories=["industrial"],
            distance_to_nearest_facility_m=200,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.INDUSTRIAL,
            land_cover_distribution={"industrial": 70, "urban": 20, "bare": 10},
            ndvi_value=0.1,
            built_up_percentage=85.0,
        )
        
        status, confidence, reasons = await engine.evaluate_cropland_fire(
            0.80, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)


class TestForestFireConfirmation(unittest.IsolatedAsyncioTestCase):
    """Test forest fire confirmation rules."""

    async def test_forest_fire_consistent(self):
        """Forest fire should be CONSISTENT with forest environment."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["forest"],
            distance_to_nearest_facility_m=None,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.FOREST,
            land_cover_distribution={"vegetation": 85, "bare": 15},
            ndvi_value=0.75,
            built_up_percentage=2.0,
        )
        
        status, confidence, reasons = await engine.evaluate_forest_fire(
            0.90, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreater(confidence, 0.6)

    async def test_forest_fire_inconsistent_with_urban(self):
        """Forest fire should be INCONSISTENT with urban environment."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[{"type": "factory"}],
            land_use_categories=["industrial", "residential"],
            distance_to_nearest_facility_m=150,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.URBAN,
            land_cover_distribution={"industrial": 60, "urban": 30, "vegetation": 10},
            ndvi_value=0.2,
            built_up_percentage=80.0,
        )
        
        status, confidence, reasons = await engine.evaluate_forest_fire(
            0.90, osm_context, landcover
        )
        
        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)


class TestConfirmationReasoning(unittest.IsolatedAsyncioTestCase):
    """Test that confirmation reasons are detailed and informative."""

    async def test_reasons_provide_evidence(self):
        """Confirmation reasons should provide specific evidence."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[{"name": "Test Refinery", "type": "refinery", "distance_m": 200}],
            land_use_categories=["industrial"],
            distance_to_nearest_facility_m=200,
        )
        
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.INDUSTRIAL,
            land_cover_distribution={"industrial": 70, "bare": 30},
            ndvi_value=0.15,
            built_up_percentage=65.0,
        )
        
        status, confidence, reasons = await engine.evaluate_industrial_fire(
            0.85, osm_context, landcover
        )
        
        # Should have multiple reasons explaining the verdict
        self.assertGreater(len(reasons), 0)
        
        # Reasons should have descriptive text
        for reason in reasons:
            self.assertTrue(len(reason.description) > 10)
            self.assertIn(reason.category, [
                "facility", "landcover", "vegetation", "classification", "satellite_status"
            ])


class TestStep8To10Rules(unittest.IsolatedAsyncioTestCase):
    """Specific tests for Steps 8, 9, and 10 requirements."""

    async def test_step8_9_buffer_percentages(self):
        """Step 9: Calculate % built-up, % cropland, % vegetation, % bare."""
        analyzer = LandCoverAnalyzer()
        
        # Mixed environment
        indices = {"NDVI": 0.45, "NDBI": 0.15, "NDMI": -0.05}
        facilities = []
        land_use = {"farmland": 3, "agricultural": 1}
        
        dist = await analyzer.get_landcover_distribution(
            28.6, 77.2, indices, facilities, land_use
        )
        
        # Keys specified in Step 9
        self.assertIn("built_up", dist)
        self.assertIn("cropland", dist)
        self.assertIn("vegetation", dist)
        self.assertIn("bare", dist)
        
        # Sum to 100%
        self.assertAlmostEqual(sum(dist.values()), 100.0, places=1)

    async def test_step10_industrial_fire_consistent(self):
        """Industrial facility nearby + built-up environment -> CONSISTENT."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[{"name": "Refinery", "type": "refinery", "distance_m": 250}],
            land_use_categories=["industrial"],
            distance_to_nearest_facility_m=250,
        )
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.INDUSTRIAL,
            land_cover_distribution={"built_up": 74.0, "cropland": 4.0, "vegetation": 8.0, "bare": 14.0},
            ndvi_value=0.15,
            built_up_percentage=74.0,
        )
        
        status, conf, reasons = await engine.evaluate_industrial_fire(
            0.87, osm_context, landcover
        )
        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(conf, 0.8)

    async def test_step10_agricultural_burn_consistent(self):
        """Cropland dominant + No industrial facility -> CONSISTENT."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["agricultural"],
            distance_to_nearest_facility_m=None,
        )
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.CROPLAND,
            land_cover_distribution={"built_up": 5.0, "cropland": 75.0, "vegetation": 15.0, "bare": 5.0},
            ndvi_value=0.55,
            built_up_percentage=5.0,
        )
        
        status, conf, reasons = await engine.evaluate_cropland_fire(
            0.82, osm_context, landcover
        )
        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(conf, 0.8)

    async def test_step10_wildfire_consistent(self):
        """Forest/vegetation dominant + No industrial facility -> CONSISTENT."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["forest"],
            distance_to_nearest_facility_m=None,
        )
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.FOREST,
            land_cover_distribution={"built_up": 2.0, "cropland": 0.0, "vegetation": 88.0, "bare": 10.0},
            ndvi_value=0.72,
            built_up_percentage=2.0,
        )
        
        status, conf, reasons = await engine.evaluate_forest_fire(
            0.91, osm_context, landcover
        )
        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(conf, 0.8)

    async def test_step10_conflicting_cropland_industrial(self):
        """Predicted Industrial, but Cropland = 80% and Industrial facility = none -> INCONSISTENT."""
        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(
            nearby_facilities=[],
            land_use_categories=["agricultural"],
            distance_to_nearest_facility_m=None,
        )
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.CROPLAND,
            land_cover_distribution={"built_up": 4.0, "cropland": 80.0, "vegetation": 10.0, "bare": 6.0},
            ndvi_value=0.60,
            built_up_percentage=4.0,
        )
        
        status, conf, reasons = await engine.evaluate_industrial_fire(
            0.87, osm_context, landcover
        )
        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)
        
        # Check reasons mention cropland contradiction and lack of facility
        descriptions = " ".join(r.description for r in reasons)
        self.assertIn("contradicts industrial fire", descriptions.lower())
        self.assertIn("no industrial facility", descriptions.lower())

    async def test_step10_cloud_coverage_handling(self):
        """Satellite image with high cloud coverage should log cloud status reason."""
        from datetime import datetime
        from backend.satellite.schemas import SentinelImageInfoSchema

        engine = ConfirmationRulesEngine()
        
        osm_context = OSMContextSchema(nearby_facilities=[], distance_to_nearest_facility_m=None)
        landcover = LandCoverContextSchema(
            dominant_land_cover=LandCoverTypeEnum.CROPLAND,
            land_cover_distribution={"cropland": 70.0, "built_up": 10.0, "vegetation": 10.0, "bare": 10.0},
            ndvi_value=0.5,
            built_up_percentage=10.0,
        )
        
        cloudy_image = SentinelImageInfoSchema(
            image_url="s3://copernicus/cloudy.tif",
            acquisition_date=datetime.fromisoformat("2026-09-13T12:00:00+00:00"),
            cloud_coverage=85.0,
            bands_available=["B02", "B03", "B04"],
            resolution_m=10,
        )
        
        status, conf, reasons = await engine.evaluate_prediction(
            PredictedClassEnum.CROPLAND_FIRE, 0.8, osm_context, landcover, sentinel_image=cloudy_image
        )
        
        cloud_reasons = [r for r in reasons if r.category == "satellite_status"]
        self.assertEqual(len(cloud_reasons), 1)
        self.assertIn("High cloud coverage (85.0%)", cloud_reasons[0].description)


if __name__ == "__main__":
    unittest.main()
