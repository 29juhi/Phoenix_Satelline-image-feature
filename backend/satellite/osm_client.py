"""
OpenStreetMap (OSM) client interface and implementation.

Handles queries to OSM to find nearby industrial/agricultural facilities and land use.
Uses Overpass API for high-performance spatial queries.
"""

import asyncio
import logging
import math
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import aiohttp
from .schemas import OSMContextSchema

logger = logging.getLogger(__name__)


class OSMClient(ABC):
    """
    Abstract interface for OpenStreetMap queries.

    Implementations will fetch facility and land-use data for geographic regions.
    """

    @abstractmethod
    async def get_nearby_facilities(
        self,
        latitude: float,
        longitude: float,
        radius_m: int = 1000,
        facility_types: Optional[List[str]] = None,
    ) -> List[dict]:
        """
        Find nearby industrial, agricultural, or other relevant facilities.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            radius_m: Search radius in meters
            facility_types: Specific OSM tags to search (e.g., ["industrial", "warehouse"])
                          If None, searches default relevant types

        Returns:
            List of facility dicts with keys:
                - type: str (facility type/OSM tag)
                - name: str (facility name if available)
                - distance_m: float (distance from center point)
                - latitude: float
                - longitude: float
                - tags: dict (raw OSM tags)

        Raises:
            Exception: If API call fails
        """
        pass

    @abstractmethod
    async def get_land_use_categories(
        self,
        latitude: float,
        longitude: float,
        radius_m: int = 1000,
    ) -> dict:
        """
        Get distribution of land use categories in area.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            radius_m: Analysis radius in meters

        Returns:
            Dict mapping land use category (str) to percentage (float)
            Example: {"industrial": 35.2, "residential": 40.1, "agricultural": 24.7}

        Raises:
            Exception: If query fails
        """
        pass

    @abstractmethod
    async def get_nearest_facility(
        self,
        latitude: float,
        longitude: float,
        facility_type: str,
        max_distance_m: int = 5000,
    ) -> Optional[dict]:
        """
        Find single nearest facility of specific type.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            facility_type: OSM tag for facility type (e.g., "industrial")
            max_distance_m: Maximum search distance

        Returns:
            Facility dict with keys: type, name, distance_m, latitude, longitude, tags
            Returns None if no facility found within max_distance_m

        Raises:
            Exception: If query fails
        """
        pass

    @abstractmethod
    async def get_full_osm_context(
        self,
        latitude: float,
        longitude: float,
        radius_m: int = 1000,
    ) -> OSMContextSchema:
        """
        Get comprehensive OSM context (facilities + land use).

        Convenience method combining get_nearby_facilities and get_land_use_categories.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            radius_m: Analysis radius in meters

        Returns:
            OSMContextSchema with facilities and land use data

        Raises:
            Exception: If any query fails
        """
        pass


class OSMClientImpl(OSMClient):
    """
    Concrete implementation of OSMClient using Overpass API.

    Provides industrial facility detection, land use analysis, and geographic queries
    via OpenStreetMap data through the Overpass API.
    """

    # Default industrial facility types to search
    DEFAULT_INDUSTRIAL_TAGS = [
        "industrial",
        "refinery",
        "factory",
        "power",
        "power_plant",
        "chemical",
        "chemical_plant",
        "warehouse",
        "mine",
        "quarry",
    ]

    # Default agricultural facility types
    DEFAULT_AGRICULTURAL_TAGS = [
        "agricultural",
        "farmland",
        "farm",
        "orchard",
        "vineyard",
        "greenhouse",
    ]

    # Land use categories that indicate agriculture
    AGRICULTURAL_LANDUSE = {"agricultural", "farmland", "orchard", "vineyard", "grass"}

    # Land use categories that indicate industrial/urban
    INDUSTRIAL_LANDUSE = {"industrial", "commercial", "construction", "warehouse"}

    # Timeout for Overpass API requests (seconds)
    REQUEST_TIMEOUT = 60

    # Rate limit: wait between requests
    REQUEST_DELAY = 0.5

    # Deduplication radius: features within this distance are considered duplicates (meters)
    DEDUP_RADIUS_M = 100

    def __init__(
        self,
        overpass_endpoint: Optional[str] = None,
        timeout_s: float = REQUEST_TIMEOUT,
    ):
        """
        Initialize OSM client.

        Args:
            overpass_endpoint: Overpass API URL. Defaults to https://overpass-api.de/api/interpreter
            timeout_s: Request timeout in seconds
        """
        self.overpass_endpoint = (
            overpass_endpoint or "https://overpass-api.de/api/interpreter"
        )
        self.timeout = timeout_s
        self._last_request_time = 0.0
        logger.info(f"OSMClientImpl initialized with endpoint: {self.overpass_endpoint}")

    @staticmethod
    def _haversine_distance(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """
        Calculate distance between two points using Haversine formula.

        Args:
            lat1, lon1: First point coordinates (degrees)
            lat2, lon2: Second point coordinates (degrees)

        Returns:
            Distance in meters
        """
        R = 6371000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(
            delta_lambda / 2
        ) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    @staticmethod
    def _latlon_to_bbox(
        latitude: float, longitude: float, radius_m: int = 1000
    ) -> Tuple[float, float, float, float]:
        """
        Convert point + radius to bounding box for Overpass queries.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            radius_m: Radius in meters

        Returns:
            Tuple of (south, west, north, east) for Overpass bbox query
        """
        # 1 degree of latitude ≈ 111 km
        # 1 degree of longitude ≈ 111 km * cos(latitude)
        lat_delta = radius_m / 111000.0
        lon_delta = radius_m / (111000.0 * math.cos(math.radians(latitude)))

        south = latitude - lat_delta
        north = latitude + lat_delta
        west = longitude - lon_delta
        east = longitude + lon_delta

        return (south, west, north, east)

    def _build_overpass_query(
        self,
        bbox: Tuple[float, float, float, float],
        tags: List[str],
        query_type: str = "way|node",
    ) -> str:
        """
        Build Overpass Query Language (QL) query for facility search.

        Args:
            bbox: Bounding box (south, west, north, east)
            tags: List of OSM tags to search for
            query_type: "way|node" to search both, or specific type

        Returns:
            Overpass QL query string
        """
        south, west, north, east = bbox

        # Build tag filters
        tag_filters = []
        for tag in tags:
            # Support both simple tags and key=value pairs
            if "=" in tag:
                tag_filters.append(f'["{tag}"]')
            else:
                # Search for tag as key with any value
                tag_filters.append(f'["{tag}"]')

        # Join multiple tag queries
        query_parts = []
        for tag in tags:
            if "=" in tag:
                key, value = tag.split("=", 1)
                query_parts.append(
                    f'({query_type}["{key}"="{value}"]({south},{west},{north},{east});)'
                )
            else:
                query_parts.append(
                    f'({query_type}["{tag}"]({south},{west},{north},{east});)'
                )

        queries = "\n".join(query_parts)

        # Full Overpass QL query
        query = f"""
[bbox:{south},{west},{north},{east}];
(
  {queries}
);
out center;
"""
        return query

    async def _query_overpass(self, query: str) -> dict:
        """
        Execute Overpass API query with rate limiting and timeout handling.

        Args:
            query: Overpass QL query string

        Returns:
            Parsed JSON response from Overpass

        Raises:
            Exception: If request fails
        """
        # Rate limiting
        elapsed = asyncio.get_event_loop().time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            await asyncio.sleep(self.REQUEST_DELAY - elapsed)

        self._last_request_time = asyncio.get_event_loop().time()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.overpass_endpoint,
                    data=query,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    if response.status == 429:
                        logger.warning("Overpass API rate limit hit (429)")
                        # Wait and retry (exponential backoff would be better in production)
                        await asyncio.sleep(5)
                        return await self._query_overpass(query)

                    if response.status != 200:
                        logger.error(f"Overpass API error {response.status}")
                        return {"elements": []}

                    return await response.json()

        except asyncio.TimeoutError:
            logger.warning(f"Overpass API timeout after {self.timeout}s")
            return {"elements": []}
        except aiohttp.ClientError as e:
            logger.error(f"Overpass API request failed: {e}")
            return {"elements": []}

    def _deduplicate_features(
        self, features: List[dict], radius_m: float = DEDUP_RADIUS_M
    ) -> List[dict]:
        """
        Remove duplicate/near-duplicate features within radius.

        Args:
            features: List of facility dicts with latitude/longitude
            radius_m: Deduplication radius in meters

        Returns:
            Deduplicated list sorted by distance to center
        """
        if not features:
            return []

        deduplicated = []
        used_ids: Set[str] = set()

        for feature in sorted(features, key=lambda x: x.get("distance_m", float("inf"))):
            osm_id = feature.get("osm_id", "")

            # Skip if we've already added this OSM element
            if osm_id in used_ids:
                continue

            # Skip if too close to an already-added feature
            is_duplicate = False
            for existing in deduplicated:
                dist = self._haversine_distance(
                    feature["latitude"],
                    feature["longitude"],
                    existing["latitude"],
                    existing["longitude"],
                )
                if dist < radius_m:
                    is_duplicate = True
                    break

            if not is_duplicate:
                deduplicated.append(feature)
                if osm_id:
                    used_ids.add(osm_id)

        return deduplicated

    async def get_nearby_facilities(
        self,
        latitude: float,
        longitude: float,
        radius_m: int = 1000,
        facility_types: Optional[List[str]] = None,
    ) -> List[dict]:
        """
        Find nearby industrial, agricultural, or other relevant facilities via Overpass API.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            radius_m: Search radius in meters
            facility_types: Specific OSM tags to search
                          If None, searches industrial + agricultural tags

        Returns:
            List of facility dicts with:
                - osm_id: str (OSM element ID)
                - name: str (facility name if available)
                - type: str (facility type/OSM tag)
                - distance_m: float (distance from center)
                - latitude: float
                - longitude: float
                - tags: dict (raw OSM tags)

        Raises:
            Exception: If query fails
        """
        if facility_types is None:
            facility_types = self.DEFAULT_INDUSTRIAL_TAGS + self.DEFAULT_AGRICULTURAL_TAGS

        bbox = self._latlon_to_bbox(latitude, longitude, radius_m)
        query = self._build_overpass_query(bbox, facility_types)

        logger.debug(
            f"Querying OSM for facilities around ({latitude}, {longitude}) within {radius_m}m"
        )

        response = await self._query_overpass(query)
        elements = response.get("elements", [])

        facilities = []
        for element in elements:
            # Extract coordinates
            # Overpass returns center for ways, and lat/lon for nodes
            elem_lat = element.get("center", {}).get("lat") or element.get("lat")
            elem_lon = element.get("center", {}).get("lon") or element.get("lon")

            if not elem_lat or not elem_lon:
                continue

            # Calculate distance
            distance = self._haversine_distance(latitude, longitude, elem_lat, elem_lon)

            # Extract facility info from tags
            tags = element.get("tags", {})
            name = tags.get("name", "Unknown")

            # Determine facility type from tags
            facility_type = "industrial"
            for tag in facility_types:
                if "=" in tag:
                    key, value = tag.split("=", 1)
                    if tags.get(key) == value:
                        facility_type = value
                        break
                else:
                    if tag in tags:
                        facility_type = tags.get(tag, tag)
                        break

            facilities.append(
                {
                    "osm_id": str(element.get("id", "")),
                    "name": name,
                    "type": facility_type,
                    "distance_m": distance,
                    "latitude": elem_lat,
                    "longitude": elem_lon,
                    "tags": tags,
                }
            )

        # Deduplicate and sort
        facilities = self._deduplicate_features(facilities, self.DEDUP_RADIUS_M)
        logger.info(f"Found {len(facilities)} facilities within {radius_m}m")

        return facilities

    async def get_land_use_categories(
        self,
        latitude: float,
        longitude: float,
        radius_m: int = 1000,
    ) -> dict:
        """
        Get distribution of land use categories in area.

        Currently uses nearby landuse/natural relations as proxy.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            radius_m: Analysis radius in meters

        Returns:
            Dict mapping land use category to count
            Example: {"industrial": 3, "agricultural": 5, "residential": 2}
        """
        bbox = self._latlon_to_bbox(latitude, longitude, radius_m)

        # Query for landuse areas
        landuse_tags = [
            "industrial",
            "agricultural",
            "residential",
            "commercial",
            "forest",
            "water",
            "grass",
            "farmland",
            "nature_reserve",
        ]
        query = self._build_overpass_query(bbox, landuse_tags, query_type="way")

        logger.debug(f"Querying OSM landuse around ({latitude}, {longitude})")

        response = await self._query_overpass(query)
        elements = response.get("elements", [])

        # Count by land use type
        land_use_counts: Dict[str, int] = {}
        for element in elements:
            tags = element.get("tags", {})
            for tag in landuse_tags:
                if tag in tags:
                    land_use_counts[tag] = land_use_counts.get(tag, 0) + 1
                    break

        logger.debug(f"Found land use distribution: {land_use_counts}")

        return land_use_counts

    async def get_nearest_facility(
        self,
        latitude: float,
        longitude: float,
        facility_type: str,
        max_distance_m: int = 5000,
    ) -> Optional[dict]:
        """
        Find single nearest facility of specific type.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            facility_type: OSM tag for facility type (e.g., "industrial", "refinery")
            max_distance_m: Maximum search distance in meters

        Returns:
            Facility dict or None if not found

        Raises:
            Exception: If query fails
        """
        facilities = await self.get_nearby_facilities(
            latitude, longitude, max_distance_m, facility_types=[facility_type]
        )

        if facilities:
            return facilities[0]  # Already sorted by distance
        return None

    async def get_full_osm_context(
        self,
        latitude: float,
        longitude: float,
        radius_m: int = 1000,
    ) -> OSMContextSchema:
        """
        Get comprehensive OSM context (facilities + land use).

        Args:
            latitude: Target latitude
            longitude: Target longitude
            radius_m: Analysis radius in meters

        Returns:
            OSMContextSchema with facilities and land use data

        Raises:
            Exception: If any query fails
        """
        logger.info(f"Fetching full OSM context for ({latitude}, {longitude})")

        # Fetch both in parallel
        facilities, land_use = await asyncio.gather(
            self.get_nearby_facilities(latitude, longitude, radius_m),
            self.get_land_use_categories(latitude, longitude, radius_m),
        )

        # Find nearest facility distance
        nearest_distance = None
        if facilities:
            nearest_distance = facilities[0].get("distance_m")

        return OSMContextSchema(
            nearby_facilities=facilities,
            land_use_categories=list(land_use.keys()),
            distance_to_nearest_facility_m=nearest_distance,
        )
