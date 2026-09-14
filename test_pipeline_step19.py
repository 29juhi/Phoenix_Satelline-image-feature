"""
STEP 19 - Full Phoenix Pipeline Test

Tests the complete pipeline:
  NASA FIRMS hotspot -> Classification -> Feature 12 -> Sentinel-2 + OSM + Land Cover -> Confirmation

Usage:
    python test_pipeline_step19.py
"""

import sys
import asyncio
import json
from datetime import datetime, timezone

sys.path.insert(0, ".")

results = []

def log(status, label, detail=""):
    icon = "OK" if status else "FAIL"
    results.append((status, label))
    line = f"  [{icon}] {label}"
    if detail:
        line += f": {detail}"
    print(line)

def test_confirmation_engine():
    print("\n===========================================")
    print("  STEP 19 - Confirmation Engine (unit)")
    print("===========================================")

    from backend.satellite.confirmation import ConfirmationRulesEngine
    engine = ConfirmationRulesEngine()

    nearby = [
        {
            "type": "industrial",
            "name": "Bharat Petroleum Refinery",
            "distance_m": 243,
            "tags": {"industrial": "refinery"},
        }
    ]
    landcover = {"built_up": 74.0, "cropland": 4.0, "vegetation": 8.0, "bare": 14.0, "water": 0.0}

    status, score, reasons, evidence = engine.evaluate_confirmation(
        predicted_class="Industrial Fire",
        classification_confidence=0.87,
        nearby_osm_features=nearby,
        landcover_percentages=landcover,
        satellite_image_available=True,
        cloud_quality=8.0,
    )

    print("\n  Scenario 1 - Industrial Fire (Delhi refinery)")
    log(status.value == "CONSISTENT", "Status = CONSISTENT", status.value)
    log(score >= 80, "Score >= 80", f"{score:.1f}")
    log(len(reasons) >= 2, f"Reasons present ({len(reasons)})")
    log(any("243" in r or "facility" in r.lower() for r in reasons), "Facility distance in reasons")
    log(any("74" in r or "built" in r.lower() for r in reasons), "Built-up % in reasons")
    log(any("cloud" in r.lower() for r in reasons), "Cloud coverage in reasons")

    print("\n  Reasons:")
    for r in reasons:
        print(f"    - {r}")
    print(f"\n  Score: {score:.1f}/100  |  Status: {status.value}")

    # Scenario 2: Agricultural Burn
    print("\n  Scenario 2 - Agricultural Burn")
    status2, score2, reasons2, _ = engine.evaluate_confirmation(
        predicted_class="Agricultural Burn",
        classification_confidence=0.78,
        nearby_osm_features=[],
        landcover_percentages={"built_up": 5.0, "cropland": 80.0, "vegetation": 10.0, "bare": 5.0, "water": 0.0},
        satellite_image_available=True,
        cloud_quality=15.0,
    )
    log(status2.value == "CONSISTENT", "Status = CONSISTENT", status2.value)
    log(score2 >= 75, "Score >= 75", f"{score2:.1f}")

    # Scenario 3: Wildfire
    print("\n  Scenario 3 - Wildfire")
    status3, score3, reasons3, _ = engine.evaluate_confirmation(
        predicted_class="Wildfire",
        classification_confidence=0.91,
        nearby_osm_features=[],
        landcover_percentages={"built_up": 3.0, "cropland": 5.0, "vegetation": 88.0, "bare": 4.0, "water": 0.0},
        satellite_image_available=True,
        cloud_quality=3.0,
    )
    log(status3.value == "CONSISTENT", "Status = CONSISTENT", status3.value)
    log(score3 >= 85, "Score >= 85", f"{score3:.1f}")

    # Scenario 4: Missing imagery -> UNCERTAIN not INCONSISTENT
    print("\n  Scenario 4 - Missing imagery")
    status4, score4, reasons4, _ = engine.evaluate_confirmation(
        predicted_class="Industrial Fire",
        classification_confidence=0.82,
        nearby_osm_features=[],
        landcover_percentages={"built_up": 30.0, "cropland": 20.0, "vegetation": 30.0, "bare": 20.0, "water": 0.0},
        satellite_image_available=False,
        cloud_quality=None,
    )
    log(status4.value != "INCONSISTENT", "Not INCONSISTENT when satellite unavailable", status4.value)
    log(any("unavailable" in r.lower() or "optical" in r.lower() for r in reasons4), "Satellite unavailability mentioned")

    # Scenario 5: Gas Flare
    print("\n  Scenario 5 - Gas Flare")
    status5, score5, _, _ = engine.evaluate_confirmation(
        predicted_class="Gas Flare",
        classification_confidence=0.79,
        nearby_osm_features=[
            {"type": "refinery", "name": "ONGC Gas Plant", "distance_m": 180, "tags": {"industrial": "oil"}}
        ],
        landcover_percentages={"built_up": 55.0, "cropland": 5.0, "vegetation": 10.0, "bare": 30.0, "water": 0.0},
        satellite_image_available=True,
        cloud_quality=20.0,
    )
    log(status5.value == "CONSISTENT", "Status = CONSISTENT", status5.value)


def test_response_format():
    print("\n===========================================")
    print("  STEP 19 - Response Format (Step 11 spec)")
    print("===========================================")

    from backend.satellite.confirmation import ConfirmationRulesEngine
    engine = ConfirmationRulesEngine()
    status, score, reasons, evidence = engine.evaluate_confirmation(
        predicted_class="Industrial Fire",
        classification_confidence=0.87,
        nearby_osm_features=[
            {"type": "industrial", "name": "Bharat Petroleum", "distance_m": 243, "tags": {"industrial": "refinery"}}
        ],
        landcover_percentages={"built_up": 74.0, "cropland": 4.0, "vegetation": 8.0, "bare": 14.0, "water": 0.0},
        satellite_image_available=True,
        cloud_quality=8.0,
    )

    response = {
        "status": status.value,
        "confirmation_score": score,
        "reasons": reasons,
        "evidence": evidence,
    }

    print(f"\n  Response JSON:")
    print(json.dumps(response, indent=4, default=str))

    log("status" in response, "Has status field")
    log("reasons" in response, "Has reasons field")
    log(isinstance(response["reasons"], list), "reasons is a list")
    log(len(response["reasons"]) >= 2, f"reasons has >=2 items ({len(response['reasons'])})")
    log("evidence" in response, "Has evidence field")
    log("confirmation_score" in response, "Has confirmation_score field")
    log(isinstance(response["confirmation_score"], (int, float)), "confirmation_score is numeric")


def test_service_pipeline():
    print("\n===========================================")
    print("  STEP 19 - Service Pipeline (mocked)")
    print("===========================================")

    import unittest.mock as mock

    from backend.satellite.service import SatelliteConfirmationService
    from backend.satellite.schemas import SatelliteConfirmationRequest, PredictedClassEnum, SentinelImageInfoSchema, OSMContextSchema

    mock_image = SentinelImageInfoSchema(
        image_url="s3://sentinel/demo/S2A_MSIL2A_20260911.tif",
        acquisition_date=datetime(2026, 9, 11, 5, 30, 0, tzinfo=timezone.utc),
        cloud_coverage=8.0,
        bands_available=["B2", "B3", "B4", "B8", "B11"],
        resolution_m=10,
    )

    mock_osm = OSMContextSchema(
        nearby_facilities=[
            {"type": "industrial", "name": "Bharat Petroleum Refinery", "distance_m": 243, "tags": {"industrial": "refinery"}}
        ],
        land_use_categories=["industrial", "built_up"],
        feature_count=1,
    )

    async def run():
        sentinel_mock = mock.AsyncMock()
        sentinel_mock.get_latest_image.return_value = mock_image
        sentinel_mock.get_spectral_indices.return_value = {"ndvi": 0.12, "ndwi": -0.3}

        osm_mock = mock.AsyncMock()
        osm_mock.get_full_osm_context.return_value = mock_osm

        from backend.satellite.landcover import LandCoverAnalyzer
        with mock.patch.object(LandCoverAnalyzer, "get_landcover_distribution", new_callable=mock.AsyncMock) as lc_mock:
            lc_mock.return_value = {
                "built_up": 74.0, "cropland": 4.0, "vegetation": 8.0, "bare": 14.0, "water": 0.0,
            }

            service = SatelliteConfirmationService(sentinel_client=sentinel_mock, osm_client=osm_mock)

            request = SatelliteConfirmationRequest(
                latitude=28.6139,
                longitude=77.2090,
                timestamp=datetime(2026, 9, 13, 14, 30, 0, tzinfo=timezone.utc),
                predicted_class=PredictedClassEnum.INDUSTRIAL_FIRE,
                classification_confidence=0.87,
            )

            return await service.confirm_hotspot(request)

    response = asyncio.run(run())

    print(f"\n  FIRE NEW INCIDENT\n")
    print(f"  Classification")
    pct = int(response.classification_confidence * 100)
    print(f"  {response.predicted_class} - {pct}%\n")
    print(f"  Satellite Confirmation")
    score_pct = int(response.confirmation_score)
    status_icon = "CONSISTENT" if response.confirmation.value == "CONSISTENT" else response.confirmation.value
    print(f"  {status_icon} - {score_pct}%\n")
    print(f"  Evidence:")
    for r in response.reasons:
        print(f"  - {r}")

    if response.nearby_facilities:
        fac = response.nearby_facilities[0]
        print(f"\n  Facility: {fac.get('name', 'Facility')} - {fac.get('distance_m', '?')}m")

    lc = response.landcover_summary
    if lc:
        print(f"  Built-up: {lc.get('built_up', 0):.0f}%")
        print(f"  Cropland: {lc.get('cropland', 0):.0f}%")

    if response.acquisition_date:
        print(f"\n  Satellite: Sentinel-2")
        print(f"  Acquired: {response.acquisition_date.strftime('%Y-%m-%d')}")
        print(f"  Cloud: {response.cloud_coverage:.0f}%")

    log(response.confirmation.value == "CONSISTENT", "Confirmation = CONSISTENT", response.confirmation.value)
    log(response.confirmation_score >= 80, "Score >= 80", f"{response.confirmation_score:.1f}")
    log(response.predicted_class == "Industrial Fire", "Original class preserved", response.predicted_class)
    log(abs(response.classification_confidence - 0.87) < 0.001, "Original confidence preserved")
    log(response.acquisition_date is not None, "Acquisition date present")
    log(response.cloud_coverage == 8.0, "Cloud coverage correct", str(response.cloud_coverage))
    log(len(response.reasons) >= 2, f"Reasons present ({len(response.reasons)})")
    log(len(response.nearby_facilities) >= 1, "Nearby facilities present")
    log(response.analysis_timestamp is not None, "Analysis timestamp present")


def main():
    print("\n")
    print("==================================================")
    print("  PHOENIX - STEP 19 FULL PIPELINE TEST")
    print("  NASA FIRMS -> Classifier -> Feature 12")
    print("==================================================")

    test_confirmation_engine()
    test_response_format()
    test_service_pipeline()

    total = len(results)
    passed = sum(1 for ok, _ in results if ok)
    failed = total - passed

    print("\n")
    print("==================================================")
    print(f"  RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print("  Failed tests:")
        for ok, label in results:
            if not ok:
                print(f"    FAIL: {label}")
        sys.exit(1)
    else:
        print("  ALL PASSED")
    print("==================================================\n")


if __name__ == "__main__":
    main()
