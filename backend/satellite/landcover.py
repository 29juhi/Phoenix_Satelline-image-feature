"""
Land cover analysis from satellite imagery and OSM context.

Processes spectral indices and facility data to determine dominant land cover type
and create detailed distribution breakdown.
"""

from typing import Optional

from .schemas import LandCoverContextSchema, LandCoverTypeEnum


# ESA WorldCover 10m Classification System Reference Mapping:
# 10: Tree cover -> forest / vegetation
# 20: Shrubland -> vegetation
# 30: Grassland -> grassland / vegetation
# 40: Cropland -> cropland
# 50: Built-up -> built_up / industrial
# 60: Bare / sparse vegetation -> bare
# 70: Snow and ice -> other
# 80: Permanent water bodies -> water
# 90: Herbaceous wetland -> water / wetland
# 95: Mangroves -> forest / vegetation
# 100: Moss and lichen -> other
ESA_WORLDCOVER_CLASSES = {
    10: {"name": "Tree cover", "category": "forest", "group": "vegetation"},
    20: {"name": "Shrubland", "category": "shrubland", "group": "vegetation"},
    30: {"name": "Grassland", "category": "grassland", "group": "vegetation"},
    40: {"name": "Cropland", "category": "cropland", "group": "cropland"},
    50: {"name": "Built-up", "category": "built_up", "group": "built_up"},
    60: {"name": "Bare / sparse vegetation", "category": "bare", "group": "bare"},
    70: {"name": "Snow and ice", "category": "snow_ice", "group": "other"},
    80: {"name": "Permanent water bodies", "category": "water", "group": "water"},
    90: {"name": "Herbaceous wetland", "category": "wetland", "group": "water"},
    95: {"name": "Mangroves", "category": "mangroves", "group": "vegetation"},
    100: {"name": "Moss and lichen", "category": "moss_lichen", "group": "other"},
}


class LandCoverDistributionDict(dict):
    """
    Dictionary for land cover distribution within hotspot buffer.
    
    Supports percentage calculations for:
    - built_up (aliased to industrial for backward compatibility)
    - cropland
    - vegetation (forest / grassland)
    - bare (bare soil / sparse vegetation)
    - water
    """

    def __getitem__(self, key):
        if key == "industrial" and not super().__contains__("industrial") and super().__contains__("built_up"):
            return super().__getitem__("built_up")
        if key == "built_up" and not super().__contains__("built_up") and super().__contains__("industrial"):
            return super().__getitem__("industrial")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "industrial" and not super().__contains__("industrial") and super().__contains__("built_up"):
            return super().__getitem__("built_up")
        if key == "built_up" and not super().__contains__("built_up") and super().__contains__("industrial"):
            return super().__getitem__("industrial")
        return super().get(key, default)

    def __contains__(self, key):
        if key == "industrial" and super().__contains__("built_up"):
            return True
        if key == "built_up" and super().__contains__("industrial"):
            return True
        return super().__contains__(key)


class LandCoverAnalyzer:
    """
    Analyzes land cover composition from satellite data and OSM context.

    Combines spectral indices (NDVI, NDBI, NDMI) with facility data to classify
    dominant land cover and generate distribution percentages.
    """

    def __init__(self):
        """Initialize land cover analyzer with classification thresholds."""
        # NDVI thresholds for vegetation classification
        self.ndvi_thresholds = {
            "dense_vegetation": 0.6,
            "moderate_vegetation": 0.4,
            "sparse_vegetation": 0.2,
            "bare_soil": 0.0,
            "water": -0.3,
        }

        # NDBI thresholds for built-up area detection
        self.ndbi_thresholds = {
            "dense_urban": 0.3,
            "moderate_urban": 0.1,
            "low_urban": 0.0,
        }

    async def classify_landcover(
        self,
        latitude: float,
        longitude: float,
        sentinel_indices: Optional[dict],
        osm_facilities: list,
        osm_land_use: dict,
    ) -> LandCoverTypeEnum:
        """
        Determine dominant land cover type.

        Decision logic (highest priority first):
        1. If industrial/warehouse facilities nearby → INDUSTRIAL
        2. Else if NDBI > dense threshold (high built-up) → URBAN
        3. Else if OSM shows significant agricultural land → CROPLAND
        4. Else if NDVI > dense threshold (dense vegetation) → FOREST
        5. Else if water indicators present → WATER
        6. Else if barren/sparse indicators → BARREN
        7. Else → GRASSLAND (default)

        Args:
            latitude: Target latitude
            longitude: Target longitude
            sentinel_indices: Dict of spectral indices {index_name: value}
            osm_facilities: List of nearby facilities from OSM
            osm_land_use: Dict of land use category distribution

        Returns:
            LandCoverTypeEnum representing dominant land cover
        """
        # Priority 1: Check for industrial facilities
        if osm_facilities:
            for facility in osm_facilities:
                facility_type = facility.get("type", "").lower()
                if any(
                    tag in facility_type
                    for tag in [
                        "industrial",
                        "refinery",
                        "factory",
                        "warehouse",
                        "power",
                        "chemical",
                    ]
                ):
                    return LandCoverTypeEnum.INDUSTRIAL
        
        # Priority 2: Check NDBI for built-up areas
        if sentinel_indices:
            ndbi = sentinel_indices.get("NDBI", -1)
            if ndbi is not None and ndbi > self.ndbi_thresholds["dense_urban"]:
                return LandCoverTypeEnum.URBAN
        
        # Priority 3: Check OSM for agricultural land
        if osm_land_use:
            agricultural_count = osm_land_use.get("agricultural", 0) + osm_land_use.get(
                "farmland", 0
            )
            if agricultural_count > 2:  # Multiple agricultural areas
                return LandCoverTypeEnum.CROPLAND
        
        # Priority 4: Check NDVI for dense vegetation
        if sentinel_indices:
            ndvi = sentinel_indices.get("NDVI", -1)
            if ndvi is not None and ndvi > self.ndvi_thresholds["dense_vegetation"]:
                return LandCoverTypeEnum.FOREST
        
        # Priority 5: Check for water
        if sentinel_indices:
            ndmi = sentinel_indices.get("NDMI", 1)  # NDMI < 0 indicates water
            if ndmi is not None and ndmi < -0.3:
                return LandCoverTypeEnum.WATER
        
        # Priority 6: Check for bare/sparse areas
        if sentinel_indices:
            ndvi = sentinel_indices.get("NDVI", -1)
            if ndvi is not None and ndvi < self.ndvi_thresholds["sparse_vegetation"]:
                return LandCoverTypeEnum.BARREN
        
        # Default: Grassland
        return LandCoverTypeEnum.GRASSLAND

    async def get_landcover_distribution(
        self,
        latitude: float,
        longitude: float,
        sentinel_indices: Optional[dict],
        osm_facilities: list,
        osm_land_use: dict,
    ) -> LandCoverDistributionDict:
        """
        Calculate percentage distribution of land cover types within hotspot buffer.

        Computes core Step 9 percentages:
        - built_up (% built-up / industrial)
        - cropland (% agricultural)
        - vegetation (% forest / shrubland / grassland)
        - bare (% bare soil / exposed earth)
        - water (% permanent water bodies)

        Uses heuristics combining spectral indices, OSM facilities, and land use.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            sentinel_indices: Dict of spectral indices
            osm_facilities: List of nearby facilities
            osm_land_use: Land use distribution from OSM

        Returns:
            LandCoverDistributionDict mapping land cover category to percentage (summing to 100)
        """
        distribution = LandCoverDistributionDict({
            "built_up": 0.0,
            "cropland": 0.0,
            "vegetation": 0.0,
            "bare": 0.0,
            "water": 0.0,
        })
        
        # Extract spectral indices
        ndvi = sentinel_indices.get("NDVI", 0) if sentinel_indices else 0
        ndbi = sentinel_indices.get("NDBI", 0) if sentinel_indices else 0
        ndmi = sentinel_indices.get("NDMI", 0) if sentinel_indices else 0
        
        # 1. Vegetation indicator (NDVI)
        if ndvi > self.ndvi_thresholds["dense_vegetation"]:
            distribution["vegetation"] = 70.0
        elif ndvi > self.ndvi_thresholds["moderate_vegetation"]:
            distribution["vegetation"] = 45.0
        elif ndvi > self.ndvi_thresholds["sparse_vegetation"]:
            distribution["vegetation"] = 20.0
        
        # 2. Built-up / Industrial indicator (NDBI)
        if ndbi > self.ndbi_thresholds["dense_urban"]:
            distribution["built_up"] = 65.0
        elif ndbi > self.ndbi_thresholds["moderate_urban"]:
            distribution["built_up"] = 40.0
        elif ndbi > self.ndbi_thresholds["low_urban"]:
            distribution["built_up"] = 15.0
        
        # 3. Water indicator (NDMI / NDWI)
        if ndmi < -0.3:
            distribution["water"] = 60.0
        elif ndmi < -0.1:
            distribution["water"] = 30.0
        
        # 4. Bare land: if vegetation, built_up, and water are minimal
        if (
            distribution["vegetation"] < 20
            and distribution["built_up"] < 20
            and distribution["water"] < 20
        ):
            distribution["bare"] = 60.0
        
        # 5. Factor in OSM agricultural land
        if osm_land_use:
            ag_count = osm_land_use.get("agricultural", 0) + osm_land_use.get("farmland", 0)
            if ag_count > 2:
                distribution["cropland"] = 50.0
                distribution["vegetation"] = max(0.0, distribution["vegetation"] - 20)
        
        # If any industrial facilities are present nearby, ensure built_up is represented
        if osm_facilities and distribution["built_up"] < 30.0:
            for fac in osm_facilities:
                fac_type = fac.get("type", "").lower()
                if any(k in fac_type for k in ["industrial", "refinery", "factory", "warehouse"]):
                    distribution["built_up"] = max(distribution["built_up"], 45.0)
                    break

        # Normalize to 100%
        total = sum(distribution.values())
        if total > 0:
            for key in list(distribution.keys()):
                distribution[key] = round((distribution[key] / total) * 100.0, 1)
            # Rebalance roundoff to exactly 100.0
            diff = 100.0 - sum(distribution.values())
            if diff != 0:
                highest_key = max(distribution, key=distribution.get)
                distribution[highest_key] = round(distribution[highest_key] + diff, 1)

        return distribution

    async def get_ndvi_value(
        self,
        sentinel_indices: Optional[dict],
    ) -> Optional[float]:
        """
        Extract NDVI from spectral indices dict.

        Args:
            sentinel_indices: Dict potentially containing NDVI key

        Returns:
            NDVI value if available, None otherwise
        """
        if sentinel_indices is None:
            return None
        return sentinel_indices.get("NDVI")

    async def calculate_built_up_percentage(
        self,
        osm_land_use: dict,
        sentinel_built_up_mask: Optional[dict],
    ) -> float:
        """
        Calculate built-up area percentage from OSM and Sentinel data.

        Combines OSM-identified urban/industrial land use with Sentinel spectral analysis.

        Args:
            osm_land_use: Land use distribution from OSM
            sentinel_built_up_mask: Built-up mask from Sentinel (if available)

        Returns:
            Built-up percentage (0-100)
        """
        built_up_pct = 0.0
        
        # OSM contribution: count industrial/residential/commercial categories
        if osm_land_use:
            urban_categories = [
                "industrial",
                "residential",
                "commercial",
                "construction",
            ]
            urban_count = sum(
                osm_land_use.get(cat, 0) for cat in urban_categories
            )
            built_up_pct += min(urban_count * 15, 50)  # Max 50% from OSM
        
        # Sentinel contribution: NDBI-based built-up detection
        if sentinel_built_up_mask:
            sentinel_built_up = sentinel_built_up_mask.get("built_up_percentage", 0)
            built_up_pct += sentinel_built_up * 0.5  # Weight Sentinel at 50%
        
        return min(built_up_pct, 100.0)

    async def create_landcover_context(
        self,
        latitude: float,
        longitude: float,
        sentinel_indices: Optional[dict],
        sentinel_built_up_mask: Optional[dict],
        osm_facilities: list,
        osm_land_use: dict,
    ) -> LandCoverContextSchema:
        """
        Create complete land cover context schema.

        Orchestrates classification, distribution, and metric calculations.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            sentinel_indices: Spectral indices from Sentinel-2
            sentinel_built_up_mask: Built-up area mask from Sentinel
            osm_facilities: Facilities from OSM
            osm_land_use: Land use distribution from OSM

        Returns:
            Populated LandCoverContextSchema
        """
        dominant = await self.classify_landcover(
            latitude, longitude, sentinel_indices, osm_facilities, osm_land_use
        )

        distribution = await self.get_landcover_distribution(
            latitude, longitude, sentinel_indices, osm_facilities, osm_land_use
        )

        ndvi = await self.get_ndvi_value(sentinel_indices)

        built_up = await self.calculate_built_up_percentage(
            osm_land_use, sentinel_built_up_mask
        )

        return LandCoverContextSchema(
            dominant_land_cover=dominant,
            land_cover_distribution=distribution,
            ndvi_value=ndvi,
            built_up_percentage=built_up,
        )
