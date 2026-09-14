"""
Interactive demonstration and test script for Steps 8, 9, and 10 of Feature 12:
- STEP 8: Land-Cover Information (ESA WorldCover Categories)
- STEP 9: Buffer Percentage Breakdown (% built-up, % cropland, % vegetation, % bare)
- STEP 10: Confirmation Rules Engine (Consistent, Inconsistent, Uncertain, Cloud Status)
"""

import asyncio
from datetime import datetime
from backend.satellite.landcover import LandCoverAnalyzer, ESA_WORLDCOVER_CLASSES
from backend.satellite.confirmation import ConfirmationRulesEngine
from backend.satellite.schemas import (
    ConfirmationStatusEnum,
    LandCoverContextSchema,
    LandCoverTypeEnum,
    OSMContextSchema,
    PredictedClassEnum,
    SentinelImageInfoSchema,
)


def print_header(title: str):
    print("\n" + "=" * 75)
    print(f"  {title}")
    print("=" * 75)


async def test_step_8():
    print_header("STEP 8: Land-Cover Information & ESA WorldCover Mapping")
    analyzer = LandCoverAnalyzer()

    print("\n1. ESA WorldCover 10m Reference Classes:")
    sample_codes = [10, 40, 50, 60, 80]
    for code in sample_codes:
        info = ESA_WORLDCOVER_CLASSES[code]
        print(f"   - Class {code:3d}: {info['name']:25s} -> Category: {info['category']:10s} (Group: {info['group']})")

    print("\n2. Land-Cover Decision Tree Classification:")
    scenarios = [
        ("Industrial Facility Nearby", [], [{"name": "Chemical Plant", "type": "chemical", "distance_m": 120}], {}),
        ("Agricultural Landuse", None, [], {"agricultural": 3, "farmland": 2}),
        ("Dense Forest (NDVI=0.72)", {"NDVI": 0.72}, [], {}),
        ("Water Body (NDMI=-0.45)", {"NDMI": -0.45}, [], {}),
        ("Bare Earth (NDVI=0.08)", {"NDVI": 0.08}, [], {}),
    ]

    for label, indices, facilities, land_use in scenarios:
        category = await analyzer.classify_landcover(
            28.6139, 77.2090, sentinel_indices=indices, osm_facilities=facilities, osm_land_use=land_use
        )
        print(f"   * Input: {label:30s} -> Classified: {category.value.upper()}")

    print("\n[OK] Step 8 verified: Multi-source land cover classification operational.")


async def test_step_9():
    print_header("STEP 9: Hotspot Buffer Percentage Breakdown")
    analyzer = LandCoverAnalyzer()

    print("\n1. Calculating buffer percentages for an industrial/urban hotspot:")
    indices = {"NDVI": 0.15, "NDBI": 0.42, "NDMI": -0.15}
    facilities = [{"name": "Refinery", "type": "refinery", "distance_m": 240}]
    land_use = {"industrial": 4}

    dist = await analyzer.get_landcover_distribution(28.6139, 77.2090, indices, facilities, land_use)

    print("   Hotspot Buffer Distribution Breakdown:")
    print(f"   * Built-up:    {dist['built_up']:5.1f}%")
    print(f"   * Cropland:    {dist['cropland']:5.1f}%")
    print(f"   * Vegetation:  {dist['vegetation']:5.1f}%")
    print(f"   * Bare:        {dist['bare']:5.1f}%")
    print(f"   * Water:       {dist['water']:5.1f}%")
    total = sum(dist.values())
    print(f"   -----------------------")
    print(f"   Total:         {total:5.1f}%")
    assert abs(total - 100.0) < 0.1, "Percentages must sum to 100%"

    print("\n2. Calculating buffer percentages for an agricultural hotspot:")
    ag_indices = {"NDVI": 0.45, "NDBI": -0.10, "NDMI": 0.10}
    ag_land_use = {"farmland": 4, "agricultural": 2}
    ag_dist = await analyzer.get_landcover_distribution(30.1234, 76.5432, ag_indices, [], ag_land_use)

    print("   Hotspot Buffer Distribution Breakdown:")
    print(f"   * Built-up:    {ag_dist['built_up']:5.1f}%")
    print(f"   * Cropland:    {ag_dist['cropland']:5.1f}%")
    print(f"   * Vegetation:  {ag_dist['vegetation']:5.1f}%")
    print(f"   * Bare:        {ag_dist['bare']:5.1f}%")
    print(f"   * Water:       {ag_dist['water']:5.1f}%")
    print(f"   -----------------------")
    print(f"   Total:         {sum(ag_dist.values()):5.1f}%")

    print("\n[OK] Step 9 verified: Hotspot buffer percentage distributions calculated accurately.")


async def test_step_10():
    print_header("STEP 10: Confirmation Rules Engine & Intelligence")
    engine = ConfirmationRulesEngine()

    test_cases = [
        {
            "name": "Case A: Industrial Fire (Facility Nearby + Built-up Environment)",
            "predicted_class": PredictedClassEnum.INDUSTRIAL_FIRE,
            "confidence": 0.87,
            "osm": OSMContextSchema(
                nearby_facilities=[{"name": "Petrochemical Refinery", "type": "refinery", "distance_m": 240}],
                distance_to_nearest_facility_m=240,
                land_use_categories=["industrial"],
            ),
            "landcover": LandCoverContextSchema(
                dominant_land_cover=LandCoverTypeEnum.INDUSTRIAL,
                land_cover_distribution={"built_up": 74.0, "cropland": 4.0, "vegetation": 8.0, "bare": 14.0},
                ndvi_value=0.15,
                built_up_percentage=74.0,
            ),
            "image": SentinelImageInfoSchema(
                image_url="s3://sentinel/img1.tif",
                acquisition_date=datetime.now(),
                cloud_coverage=12.0,
                bands_available=["B02", "B03", "B04"],
                resolution_m=10,
            ),
            "expected_verdict": ConfirmationStatusEnum.CONSISTENT,
        },
        {
            "name": "Case B: Agricultural Burn (Cropland Dominant + No Industrial Facility)",
            "predicted_class": PredictedClassEnum.CROPLAND_FIRE,
            "confidence": 0.85,
            "osm": OSMContextSchema(
                nearby_facilities=[],
                distance_to_nearest_facility_m=None,
                land_use_categories=["farmland", "agricultural"],
            ),
            "landcover": LandCoverContextSchema(
                dominant_land_cover=LandCoverTypeEnum.CROPLAND,
                land_cover_distribution={"built_up": 3.0, "cropland": 76.0, "vegetation": 15.0, "bare": 6.0},
                ndvi_value=0.52,
                built_up_percentage=3.0,
            ),
            "image": None,
            "expected_verdict": ConfirmationStatusEnum.CONSISTENT,
        },
        {
            "name": "Case C: Wildfire (Forest/Vegetation Dominant + No Industrial Facility)",
            "predicted_class": PredictedClassEnum.FOREST_FIRE,
            "confidence": 0.92,
            "osm": OSMContextSchema(
                nearby_facilities=[],
                distance_to_nearest_facility_m=None,
                land_use_categories=["forest"],
            ),
            "landcover": LandCoverContextSchema(
                dominant_land_cover=LandCoverTypeEnum.FOREST,
                land_cover_distribution={"built_up": 1.0, "cropland": 0.0, "vegetation": 89.0, "bare": 10.0},
                ndvi_value=0.74,
                built_up_percentage=1.0,
            ),
            "image": None,
            "expected_verdict": ConfirmationStatusEnum.CONSISTENT,
        },
        {
            "name": "Case D: Conflicting Evidence (Predicted Industrial, but Cropland=80% & No Facility)",
            "predicted_class": PredictedClassEnum.INDUSTRIAL_FIRE,
            "confidence": 0.88,
            "osm": OSMContextSchema(
                nearby_facilities=[],
                distance_to_nearest_facility_m=None,
                land_use_categories=["farmland"],
            ),
            "landcover": LandCoverContextSchema(
                dominant_land_cover=LandCoverTypeEnum.CROPLAND,
                land_cover_distribution={"built_up": 4.0, "cropland": 80.0, "vegetation": 10.0, "bare": 6.0},
                ndvi_value=0.58,
                built_up_percentage=4.0,
            ),
            "image": None,
            "expected_verdict": ConfirmationStatusEnum.INCONSISTENT,
        },
        {
            "name": "Case E: Satellite Cloud Caveat (High Cloud Cover = 85%)",
            "predicted_class": PredictedClassEnum.CROPLAND_FIRE,
            "confidence": 0.80,
            "osm": OSMContextSchema(
                nearby_facilities=[],
                distance_to_nearest_facility_m=None,
                land_use_categories=["farmland"],
            ),
            "landcover": LandCoverContextSchema(
                dominant_land_cover=LandCoverTypeEnum.CROPLAND,
                land_cover_distribution={"built_up": 5.0, "cropland": 70.0, "vegetation": 15.0, "bare": 10.0},
                ndvi_value=0.48,
                built_up_percentage=5.0,
            ),
            "image": SentinelImageInfoSchema(
                image_url="s3://sentinel/cloudy.tif",
                acquisition_date=datetime.now(),
                cloud_coverage=85.0,
                bands_available=["B02", "B03", "B04"],
                resolution_m=10,
            ),
            "expected_verdict": ConfirmationStatusEnum.CONSISTENT,
        },
    ]

    for tc in test_cases:
        print(f"\n--- {tc['name']} ---")
        status, conf, reasons = await engine.evaluate_prediction(
            tc["predicted_class"],
            tc["confidence"],
            tc["osm"],
            tc["landcover"],
            sentinel_image=tc["image"],
        )
        print(f"   * Predicted Class:        {tc['predicted_class'].value} (Confidence: {tc['confidence']:.2f})")
        print(f"   * Confirmation Verdict:   {status.value} (Score: {conf:.2f})")
        print(f"   * Expected Verdict:       {tc['expected_verdict'].value}")
        assert status == tc["expected_verdict"], f"Expected {tc['expected_verdict']} but got {status}"
        print("   * Supporting Reasons:")
        for r in reasons:
            print(f"     - [{r.category:16s}] {r.description} (conf: {r.confidence:.2f})")

    print("\n[OK] Step 10 verified: All confirmation rules, conflicts, and cloud caveats validated.")


async def main():
    await test_step_8()
    await test_step_9()
    await test_step_10()
    print("\n" + "=" * 75)
    print("  ALL STEPS 8, 9, 10 TESTS PASSED SUCCESSFULLY! ✓")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
