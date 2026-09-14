"""
Unit tests for Step 11 & Step 12: Rule-Based Confirmation Engine.
"""

import unittest
from backend.satellite.confirmation import ConfirmationRulesEngine
from backend.satellite.schemas import ConfirmationStatusEnum, PredictedClassEnum


class TestConfirmationEngineStep11And12(unittest.TestCase):
    """Test suite for ConfirmationRulesEngine."""

    def setUp(self):
        self.engine = ConfirmationRulesEngine()

    def test_industrial_fire_consistent(self):
        """Industrial Fire: facility nearby + built-up land dominates -> CONSISTENT."""
        facilities = [{"name": "Chemical Plant", "type": "chemical", "distance_m": 240}]
        percentages = {"built_up": 72.0, "cropland": 5.0, "vegetation": 10.0, "bare": 13.0}
        
        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Industrial Fire",
            classification_confidence=0.88,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=15.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(score, 65.0)
        self.assertIsInstance(reasons, list)
        self.assertTrue(all(isinstance(r, str) for r in reasons))
        self.assertIsInstance(evidence, dict)
        self.assertTrue(evidence["has_industrial_facility"])
        
        reasons_text = " ".join(reasons)
        self.assertIn("Chemical Plant", reasons_text)
        self.assertIn("consistent with", reasons_text.lower())

    def test_industrial_fire_inconsistent_with_cropland(self):
        """Industrial Fire: cropland dominates (80%) + no facility -> INCONSISTENT."""
        facilities = []
        percentages = {"built_up": 4.0, "cropland": 80.0, "vegetation": 10.0, "bare": 6.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Industrial Fire",
            classification_confidence=0.85,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=10.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)
        self.assertLessEqual(score, 35.0)
        reasons_text = " ".join(reasons)
        self.assertIn("inconsistent with industrial fire", reasons_text.lower())
        self.assertIn("no industrial facility detected", reasons_text.lower())

    def test_missing_satellite_does_not_solely_fail(self):
        """If satellite imagery is unavailable, return UNCERTAIN rather than INCONSISTENT when evidence is insufficient."""
        facilities = []
        # Mixed neutral land cover
        percentages = {"built_up": 25.0, "cropland": 25.0, "vegetation": 25.0, "bare": 25.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Industrial Fire",
            classification_confidence=0.70,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=False,
            cloud_quality=None,
        )

        self.assertEqual(status, ConfirmationStatusEnum.UNCERTAIN)
        reasons_text = " ".join(reasons)
        self.assertIn("unavailable", reasons_text.lower())

    def test_gas_flare_consistent(self):
        """Gas Flare: refinery/oil/gas nearby + cleared/built-up ground -> CONSISTENT."""
        facilities = [{"name": "Oil Refinery Flare", "type": "refinery", "distance_m": 180}]
        percentages = {"built_up": 55.0, "cropland": 5.0, "vegetation": 10.0, "bare": 30.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Gas Flare",
            classification_confidence=0.91,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=5.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(score, 65.0)
        self.assertTrue(evidence["has_gas_facility"])
        reasons_text = " ".join(reasons)
        self.assertIn("consistent with gas flaring", reasons_text.lower())

    def test_gas_flare_inconsistent_in_forest(self):
        """Gas Flare: in dense forest with no oil/gas facility -> INCONSISTENT."""
        facilities = []
        percentages = {"built_up": 2.0, "cropland": 0.0, "vegetation": 88.0, "bare": 10.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Gas Flare",
            classification_confidence=0.80,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=10.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)
        reasons_text = " ".join(reasons)
        self.assertIn("inconsistent with gas flare", reasons_text.lower())

    def test_agricultural_burn_consistent(self):
        """Agricultural Burn: cropland dominates + no facility -> CONSISTENT."""
        facilities = []
        percentages = {"built_up": 2.0, "cropland": 78.0, "vegetation": 12.0, "bare": 8.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Agricultural Burn",
            classification_confidence=0.86,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=12.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(score, 65.0)
        reasons_text = " ".join(reasons)
        self.assertIn("consistent with agricultural burn", reasons_text.lower())

    def test_agricultural_burn_inconsistent_with_industrial(self):
        """Agricultural Burn: factory nearby + high built-up -> INCONSISTENT."""
        facilities = [{"name": "Automobile Assembly", "type": "factory", "distance_m": 120}]
        percentages = {"built_up": 75.0, "cropland": 5.0, "vegetation": 10.0, "bare": 10.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Agricultural Burn",
            classification_confidence=0.84,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=15.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)
        reasons_text = " ".join(reasons)
        self.assertIn("inconsistent with agricultural burn", reasons_text.lower())

    def test_wildfire_consistent(self):
        """Wildfire: forest dominates + no industrial facility -> CONSISTENT."""
        facilities = []
        percentages = {"built_up": 1.0, "cropland": 0.0, "vegetation": 89.0, "bare": 10.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Wildfire",
            classification_confidence=0.92,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=20.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(score, 65.0)
        reasons_text = " ".join(reasons)
        self.assertIn("consistent with wildfire", reasons_text.lower())

    def test_wildfire_inconsistent_in_industrial(self):
        """Wildfire: dense industrial park -> INCONSISTENT."""
        facilities = [{"name": "Steel Foundry", "type": "factory", "distance_m": 150}]
        percentages = {"built_up": 80.0, "cropland": 0.0, "vegetation": 5.0, "bare": 15.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Wildfire",
            classification_confidence=0.80,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=10.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.INCONSISTENT)
        reasons_text = " ".join(reasons)
        self.assertIn("inconsistent with wildfire", reasons_text.lower())

    def test_mining_consistent(self):
        """Mining: quarry/mine facility + bare earth -> CONSISTENT."""
        facilities = [{"name": "Limestone Quarry", "type": "quarry", "distance_m": 350}]
        percentages = {"built_up": 10.0, "cropland": 5.0, "vegetation": 15.0, "bare": 70.0}

        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Mining",
            classification_confidence=0.89,
            nearby_osm_features=facilities,
            landcover_percentages=percentages,
            satellite_image_available=True,
            cloud_quality=15.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.CONSISTENT)
        self.assertGreaterEqual(score, 65.0)
        self.assertTrue(evidence["has_mining_facility"])
        reasons_text = " ".join(reasons)
        self.assertIn("consistent with mining", reasons_text.lower())

    def test_unknown_class_returns_uncertain(self):
        """Unknown class -> UNCERTAIN."""
        status, score, reasons, evidence = self.engine.evaluate_confirmation(
            predicted_class="Unknown",
            classification_confidence=0.50,
            nearby_osm_features=[],
            landcover_percentages={"built_up": 20.0, "cropland": 20.0, "vegetation": 40.0, "bare": 20.0},
            satellite_image_available=True,
            cloud_quality=10.0,
        )

        self.assertEqual(status, ConfirmationStatusEnum.UNCERTAIN)
        self.assertEqual(score, 50.0)


if __name__ == "__main__":
    unittest.main()
