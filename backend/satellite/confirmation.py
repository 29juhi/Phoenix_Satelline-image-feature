"""
Deterministic rule-based Satellite Confirmation Engine for Phoenix Feature 12.

Evaluates satellite context, OSM facilities, and land cover against predicted fire classifications.
Supports:
- Industrial Fire
- Gas Flare
- Agricultural Burn (and Cropland Fire)
- Wildfire (and Forest Fire)
- Mining
- Unknown (and Uncertain)

Never modifies the original fire classification or confidence.
Produces explainable reasons with "consistent with" and "inconsistent with" wording.
"""

from typing import List, Optional, Tuple, Union

from .schemas import (
    ConfirmationReasonSchema,
    ConfirmationStatusEnum,
    LandCoverContextSchema,
    LandCoverTypeEnum,
    OSMContextSchema,
    PredictedClassEnum,
    SentinelImageInfoSchema,
)


class ConfirmationRulesEngine:
    """
    Deterministic rule-based Satellite Confirmation Engine for Phoenix Feature 12.

    Receives:
    - predicted_class
    - classification_confidence
    - nearby_osm_features
    - landcover_percentages
    - satellite_image_available
    - cloud_quality

    Returns:
    - status: CONSISTENT | INCONSISTENT | UNCERTAIN
    - confirmation_score: 0-100
    - reasons: list[str]
    - evidence: structured dictionary
    """

    def __init__(self):
        """Initialize confirmation rules and distance/landcover thresholds."""
        # Distance thresholds
        self.facility_relevance_threshold_m = 500  # Within 500m is relevant
        self.mining_relevance_threshold_m = 1000  # Mining sites can be large (1000m)
        self.near_facility_threshold_m = 100

        # Percentage thresholds
        self.high_coverage_threshold = 60.0  # >60% is significant/dominant
        self.moderate_coverage_threshold = 40.0  # >40% is substantial
        self.low_coverage_threshold = 10.0  # <10% is low

        # Cloud cover threshold
        self.max_reliable_cloud_cover = 70.0  # >70% cloud coverage limits optical validation

    # =========================================================================
    # Primary Step 12 Engine Method
    # =========================================================================

    def evaluate_confirmation(
        self,
        predicted_class: Union[str, PredictedClassEnum],
        classification_confidence: float,
        nearby_osm_features: List[dict],
        landcover_percentages: dict,
        satellite_image_available: bool = True,
        cloud_quality: Optional[Union[float, dict]] = None,
    ) -> Tuple[ConfirmationStatusEnum, float, List[str], dict]:
        """
        Evaluate fire confirmation using deterministic rules.

        Args:
            predicted_class: Predicted class name or enum
            classification_confidence: Model confidence score (0.0 to 1.0)
            nearby_osm_features: List of nearby facilities / OSM elements
            landcover_percentages: Dict of percentages (built_up, cropland, vegetation, bare, water)
            satellite_image_available: Whether satellite optical imagery is available
            cloud_quality: Cloud coverage percentage (float) or metadata dict

        Returns:
            Tuple of:
            - status (ConfirmationStatusEnum: CONSISTENT | INCONSISTENT | UNCERTAIN)
            - confirmation_score (float: 0 to 100)
            - reasons (List[str]: detailed human-readable explanation sentences)
            - evidence (dict: structured metrics driving decision)
        """
        # 1. Normalize predicted class
        norm_class = self._normalize_class(predicted_class)

        # 2. Extract land-cover percentages (with aliases)
        built_up_pct = float(landcover_percentages.get("built_up", landcover_percentages.get("industrial", 0.0)))
        cropland_pct = float(landcover_percentages.get("cropland", 0.0))
        vegetation_pct = float(landcover_percentages.get("vegetation", 0.0))
        bare_pct = float(landcover_percentages.get("bare", 0.0))
        water_pct = float(landcover_percentages.get("water", 0.0))

        # 3. Extract cloud coverage percentage
        cloud_coverage = None
        if isinstance(cloud_quality, (int, float)):
            cloud_coverage = float(cloud_quality)
        elif isinstance(cloud_quality, dict):
            cloud_coverage = cloud_quality.get("cloud_coverage")

        # 4. Analyze OSM facilities
        has_industrial, nearest_ind_dist, nearest_ind_name = self._find_nearest_feature(
            nearby_osm_features,
            tags=["industrial", "refinery", "factory", "power", "power_plant", "chemical", "chemical_plant", "warehouse", "commercial"],
            max_dist_m=self.facility_relevance_threshold_m,
        )

        has_gas, nearest_gas_dist, nearest_gas_name = self._find_nearest_feature(
            nearby_osm_features,
            tags=["refinery", "oil", "gas", "petrochemical", "flare", "pipeline", "gas_plant"],
            max_dist_m=self.facility_relevance_threshold_m,
        )

        has_mining, nearest_mine_dist, nearest_mine_name = self._find_nearest_feature(
            nearby_osm_features,
            tags=["mine", "quarry", "mining", "mineral", "gravel_pit"],
            max_dist_m=self.mining_relevance_threshold_m,
        )

        # Build structured evidence dictionary
        evidence = {
            "predicted_class": norm_class,
            "classification_confidence": classification_confidence,
            "built_up_percentage": built_up_pct,
            "cropland_percentage": cropland_pct,
            "vegetation_percentage": vegetation_pct,
            "bare_percentage": bare_pct,
            "water_percentage": water_pct,
            "satellite_image_available": satellite_image_available,
            "cloud_coverage": cloud_coverage,
            "has_industrial_facility": has_industrial,
            "nearest_industrial_facility": nearest_ind_name,
            "nearest_industrial_distance_m": nearest_ind_dist,
            "has_gas_facility": has_gas,
            "nearest_gas_facility": nearest_gas_name,
            "nearest_gas_distance_m": nearest_gas_dist,
            "has_mining_facility": has_mining,
            "nearest_mining_facility": nearest_mine_name,
            "nearest_mining_distance_m": nearest_mine_dist,
        }

        reasons: List[str] = []
        score = 50.0  # Start from neutral

        # Satellite optical availability explanation
        if not satellite_image_available:
            reasons.append("Satellite optical imagery currently unavailable; confirmation relies on OSM and land-cover context")
        elif cloud_coverage is not None:
            if cloud_coverage <= 30.0:
                reasons.append(f"Satellite image available with acceptable cloud coverage ({cloud_coverage:.1f}%)")
            elif cloud_coverage > self.max_reliable_cloud_cover:
                reasons.append(f"High cloud coverage ({cloud_coverage:.1f}%) limits optical surface confirmation")

        # 5. Apply Class-Specific Rules
        if norm_class == "Industrial Fire":
            score, rule_reasons = self._rule_industrial_fire(
                has_industrial, nearest_ind_dist, nearest_ind_name,
                built_up_pct, cropland_pct, vegetation_pct
            )
            reasons.extend(rule_reasons)

        elif norm_class == "Gas Flare":
            score, rule_reasons = self._rule_gas_flare(
                has_gas, nearest_gas_dist, nearest_gas_name,
                has_industrial, nearest_ind_dist, nearest_ind_name,
                built_up_pct, bare_pct, cropland_pct, vegetation_pct
            )
            reasons.extend(rule_reasons)

        elif norm_class in ["Agricultural Burn", "Cropland Fire"]:
            score, rule_reasons = self._rule_agricultural_burn(
                has_industrial, nearest_ind_dist, nearest_ind_name,
                cropland_pct, built_up_pct
            )
            reasons.extend(rule_reasons)

        elif norm_class in ["Wildfire", "Forest Fire"]:
            score, rule_reasons = self._rule_wildfire(
                has_industrial, nearest_ind_dist, nearest_ind_name,
                vegetation_pct, built_up_pct
            )
            reasons.extend(rule_reasons)

        elif norm_class == "Mining":
            score, rule_reasons = self._rule_mining(
                has_mining, nearest_mine_dist, nearest_mine_name,
                bare_pct, built_up_pct, cropland_pct
            )
            reasons.extend(rule_reasons)

        else:
            # Unknown / Uncertain
            score = 50.0
            reasons.append("Initial fire classification is Unknown or uncertain; physical consistency cannot be established")

        # 6. Final Status & Score Resolution
        final_score = max(0.0, min(100.0, round(score, 1)))

        if norm_class in ["Unknown", "Uncertain"]:
            status = ConfirmationStatusEnum.UNCERTAIN
        elif final_score >= 65.0:
            status = ConfirmationStatusEnum.CONSISTENT
        elif final_score <= 35.0:
            # Rule: If satellite imagery is unavailable, do not mark INCONSISTENT solely for missing imagery
            if not satellite_image_available and (cropland_pct < 60.0 and vegetation_pct < 60.0 and built_up_pct < 60.0):
                status = ConfirmationStatusEnum.UNCERTAIN
                reasons.append("Evidence is insufficient to confirm or reject without optical satellite verification; marked UNCERTAIN")
            else:
                status = ConfirmationStatusEnum.INCONSISTENT
        else:
            status = ConfirmationStatusEnum.UNCERTAIN

        return status, final_score, reasons, evidence

    # =========================================================================
    # Rule Implementations
    # =========================================================================

    def _rule_industrial_fire(
        self,
        has_facility: bool,
        dist_m: Optional[float],
        name: Optional[str],
        built_up_pct: float,
        cropland_pct: float,
        vegetation_pct: float,
    ) -> Tuple[float, List[str]]:
        score = 50.0
        reasons = []

        # Facility check
        if has_facility:
            score += 35.0
            reasons.append(f"Industrial facility ({name}) located {dist_m:.0f}m from hotspot, consistent with industrial fire")
        else:
            reasons.append("No industrial facility detected within 500m buffer")

        # Built-up check
        if built_up_pct >= self.high_coverage_threshold:
            score += 25.0
            reasons.append(f"Built-up/industrial land dominates the surrounding area ({built_up_pct:.1f}%), consistent with industrial fire")
        elif built_up_pct <= self.low_coverage_threshold:
            score -= 25.0
            reasons.append(f"Very low built-up coverage ({built_up_pct:.1f}%) is inconsistent with industrial fire")

        # Cropland check
        if cropland_pct >= 50.0:
            score -= 35.0
            reasons.append(f"Cropland dominates the surrounding area ({cropland_pct:.1f}%), contradicts industrial fire and is inconsistent with industrial setting")

        # Forest/vegetation check
        if vegetation_pct >= 50.0:
            score -= 35.0
            reasons.append(f"Forest/vegetation dominates the surrounding area ({vegetation_pct:.1f}%), inconsistent with industrial fire")

        return score, reasons

    def _rule_gas_flare(
        self,
        has_gas: bool,
        gas_dist_m: Optional[float],
        gas_name: Optional[str],
        has_industrial: bool,
        ind_dist_m: Optional[float],
        ind_name: Optional[str],
        built_up_pct: float,
        bare_pct: float,
        cropland_pct: float,
        vegetation_pct: float,
    ) -> Tuple[float, List[str]]:
        score = 50.0
        reasons = []

        if has_gas:
            score += 45.0
            reasons.append(f"Oil/gas or refinery facility ({gas_name}) located {gas_dist_m:.0f}m from hotspot, consistent with gas flaring")
        elif has_industrial:
            score += 25.0
            reasons.append(f"Industrial facility ({ind_name}) located {ind_dist_m:.0f}m from hotspot, potentially consistent with flaring")
        else:
            reasons.append("No oil/gas or industrial facility detected within 500m buffer")

        if built_up_pct >= 40.0 or bare_pct >= 40.0:
            score += 20.0
            reasons.append(f"Industrial built-up ({built_up_pct:.1f}%) or cleared ground context consistent with gas flare site")

        if cropland_pct >= 60.0 and not has_gas:
            score -= 40.0
            reasons.append(f"Cropland dominates ({cropland_pct:.1f}%) with no flare infrastructure, inconsistent with gas flare")

        if vegetation_pct >= 60.0 and not has_gas:
            score -= 40.0
            reasons.append(f"Dense natural vegetation ({vegetation_pct:.1f}%) without gas infrastructure is inconsistent with gas flare")

        return score, reasons

    def _rule_agricultural_burn(
        self,
        has_facility: bool,
        dist_m: Optional[float],
        name: Optional[str],
        cropland_pct: float,
        built_up_pct: float,
    ) -> Tuple[float, List[str]]:
        score = 50.0
        reasons = []

        # Cropland check
        if cropland_pct >= self.moderate_coverage_threshold:
            score += 40.0
            reasons.append(f"Cropland dominates the surrounding area ({cropland_pct:.1f}%), consistent with agricultural burn")
        elif cropland_pct <= self.low_coverage_threshold:
            score -= 25.0
            reasons.append(f"Low cropland coverage ({cropland_pct:.1f}%) inconsistent with agricultural burning")

        # Dense industrial check
        if has_facility and dist_m is not None:
            score -= 40.0
            reasons.append(f"Industrial facility ({name}) detected within {dist_m:.0f}m, inconsistent with agricultural burn")
        else:
            reasons.append("No industrial facility detected within 500m buffer")

        if built_up_pct >= self.high_coverage_threshold:
            score -= 30.0
            reasons.append(f"Dense industrial/built-up environment ({built_up_pct:.1f}%) is inconsistent with agricultural burn")

        return score, reasons

    def _rule_wildfire(
        self,
        has_facility: bool,
        dist_m: Optional[float],
        name: Optional[str],
        vegetation_pct: float,
        built_up_pct: float,
    ) -> Tuple[float, List[str]]:
        score = 50.0
        reasons = []

        # Forest/vegetation check
        if vegetation_pct >= 50.0:
            score += 45.0
            reasons.append(f"Forest/vegetation dominates the surrounding area ({vegetation_pct:.1f}%), consistent with wildfire")
        elif vegetation_pct <= self.low_coverage_threshold:
            score -= 30.0
            reasons.append(f"Low vegetation coverage ({vegetation_pct:.1f}%) is inconsistent with wildfire")

        # Dense industrial check
        if has_facility and dist_m is not None:
            score -= 45.0
            reasons.append(f"Industrial facility ({name}) located {dist_m:.0f}m from hotspot, inconsistent with wildfire")
        else:
            reasons.append("No industrial facility detected within 500m buffer")

        if built_up_pct >= self.high_coverage_threshold:
            score -= 30.0
            reasons.append(f"Dense built-up environment ({built_up_pct:.1f}%) is inconsistent with wildfire")

        return score, reasons

    def _rule_mining(
        self,
        has_mining: bool,
        dist_m: Optional[float],
        name: Optional[str],
        bare_pct: float,
        built_up_pct: float,
        cropland_pct: float,
    ) -> Tuple[float, List[str]]:
        score = 50.0
        reasons = []

        if has_mining:
            score += 45.0
            reasons.append(f"Mining/quarry facility ({name}) located {dist_m:.0f}m from hotspot, consistent with mining activity")
        else:
            reasons.append("No mining or quarry facility detected within 1000m buffer")

        if bare_pct >= 40.0:
            score += 25.0
            reasons.append(f"High percentage of bare/excavated ground ({bare_pct:.1f}%) consistent with mining operations")

        if cropland_pct >= self.high_coverage_threshold and not has_mining:
            score -= 35.0
            reasons.append(f"Surrounding area is predominantly cropland ({cropland_pct:.1f}%) with no extraction site, inconsistent with mining")

        if built_up_pct >= 60.0 and not has_mining:
            score -= 30.0
            reasons.append(f"High urban built-up coverage ({built_up_pct:.1f}%) inconsistent with open-pit mining")

        return score, reasons

    # =========================================================================
    # Helpers
    # =========================================================================

    def _normalize_class(self, predicted_class: Union[str, PredictedClassEnum]) -> str:
        """Normalize predicted class string."""
        if isinstance(predicted_class, PredictedClassEnum):
            raw = predicted_class.value
        else:
            raw = str(predicted_class)

        low = raw.strip().lower()
        if "industrial" in low:
            return "Industrial Fire"
        elif "flare" in low or "gas" in low:
            return "Gas Flare"
        elif "agri" in low or "crop" in low:
            return "Agricultural Burn"
        elif "wild" in low or "forest" in low:
            return "Wildfire"
        elif "min" in low or "quarry" in low:
            return "Mining"
        elif "unknown" in low or "uncertain" in low:
            return "Unknown"
        return raw.strip()

    def _find_nearest_feature(
        self,
        features: List[dict],
        tags: List[str],
        max_dist_m: float,
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """Find nearest feature matching tags within max_dist_m."""
        if not features:
            return False, None, None

        matching = []
        for f in features:
            f_type = str(f.get("type", "")).lower()
            f_tags = f.get("tags", {})
            f_dist = f.get("distance_m", float("inf"))

            # Check type or any tag value
            matches = any(t in f_type for t in tags) or any(
                t in str(v).lower() for k, v in f_tags.items() if isinstance(v, str) for t in tags
            )
            if matches and f_dist <= max_dist_m:
                matching.append((f_dist, f.get("name") or f_type or "Facility"))

        if not matching:
            return False, None, None

        matching.sort(key=lambda x: x[0])
        best_dist, best_name = matching[0]
        return True, best_dist, best_name

    def _create_reason(
        self,
        category: str,
        description: str,
        confidence: float = 1.0,
    ) -> ConfirmationReasonSchema:
        """Helper to create ConfirmationReasonSchema."""
        return ConfirmationReasonSchema(
            category=category,
            description=description,
            confidence=confidence,
        )

    # =========================================================================
    # Backward Compatibility Adapter for Existing Tests
    # =========================================================================

    async def evaluate_prediction(
        self,
        predicted_class: PredictedClassEnum,
        predicted_confidence: float,
        osm_context: OSMContextSchema,
        landcover_context: LandCoverContextSchema,
        sentinel_image: Optional[SentinelImageInfoSchema] = None,
    ) -> Tuple[ConfirmationStatusEnum, float, List[ConfirmationReasonSchema]]:
        """
        Adapter method preserving existing test and service contract.
        
        Calls evaluate_confirmation and converts output to ConfirmationReasonSchema list.
        """
        satellite_available = sentinel_image is not None
        cloud_quality = sentinel_image.cloud_coverage if sentinel_image else None

        status, score, str_reasons, evidence = self.evaluate_confirmation(
            predicted_class=predicted_class,
            classification_confidence=predicted_confidence,
            nearby_osm_features=osm_context.nearby_facilities,
            landcover_percentages=landcover_context.land_cover_distribution,
            satellite_image_available=satellite_available,
            cloud_quality=cloud_quality,
        )

        schema_reasons: List[ConfirmationReasonSchema] = []
        for r_str in str_reasons:
            cat = "landcover"
            if "facility" in r_str.lower() or "industrial facility" in r_str.lower():
                cat = "facility"
            elif "vegetation" in r_str.lower() or "forest" in r_str.lower():
                cat = "vegetation"
            elif "satellite" in r_str.lower() or "cloud" in r_str.lower():
                cat = "satellite_status"
            elif "unknown" in r_str.lower() or "uncertain" in r_str.lower():
                cat = "classification"
            schema_reasons.append(self._create_reason(cat, r_str, confidence=score / 100.0 if score > 0 else 0.8))

        return status, score / 100.0, schema_reasons

    async def evaluate_industrial_fire(
        self,
        predicted_confidence: float,
        osm_context: OSMContextSchema,
        landcover_context: LandCoverContextSchema,
        sentinel_image: Optional[SentinelImageInfoSchema] = None,
    ) -> Tuple[ConfirmationStatusEnum, float, List[ConfirmationReasonSchema]]:
        return await self.evaluate_prediction(
            PredictedClassEnum.INDUSTRIAL_FIRE, predicted_confidence, osm_context, landcover_context, sentinel_image
        )

    async def evaluate_cropland_fire(
        self,
        predicted_confidence: float,
        osm_context: OSMContextSchema,
        landcover_context: LandCoverContextSchema,
        sentinel_image: Optional[SentinelImageInfoSchema] = None,
    ) -> Tuple[ConfirmationStatusEnum, float, List[ConfirmationReasonSchema]]:
        return await self.evaluate_prediction(
            PredictedClassEnum.CROPLAND_FIRE, predicted_confidence, osm_context, landcover_context, sentinel_image
        )

    async def evaluate_forest_fire(
        self,
        predicted_confidence: float,
        osm_context: OSMContextSchema,
        landcover_context: LandCoverContextSchema,
        sentinel_image: Optional[SentinelImageInfoSchema] = None,
    ) -> Tuple[ConfirmationStatusEnum, float, List[ConfirmationReasonSchema]]:
        return await self.evaluate_prediction(
            PredictedClassEnum.FOREST_FIRE, predicted_confidence, osm_context, landcover_context, sentinel_image
        )
