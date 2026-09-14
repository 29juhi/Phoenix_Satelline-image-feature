"""
Sentinel-2 satellite image client interface.

Handles retrieval of Sentinel-2 imagery for given coordinates and date.
Currently defines interfaces only - actual API implementation deferred.

OAuth2 Authentication:
- Uses Sentinel Hub OAuth2 endpoint
- Caches access tokens to avoid repeated authentication
- Reads credentials from environment variables (never logged)

Image Retrieval:
- Uses Sentinel Hub Processing API and STAC API
- Converts hotspot coordinates to bounding box (512m x 512m)
- Searches for cloud-free imagery within ±5 days of event
- Caches retrieved images to minimize API calls
- Returns PNG/JPEG with metadata
"""

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from .schemas import SentinelImageInfoSchema


class SentinelHubAuth:
    """
    Sentinel Hub OAuth2 authentication handler.

    Obtains and caches access tokens from Sentinel Hub OAuth endpoint.
    Handles token expiration and refresh automatically.

    Environment variables required:
    - SENTINEL_HUB_CLIENT_ID: OAuth2 client ID
    - SENTINEL_HUB_CLIENT_SECRET: OAuth2 client secret (never logged)
    """

    # Sentinel Hub OAuth2 endpoint
    TOKEN_ENDPOINT = "https://identity.dataspace.copernicus.eu/oauth/token"

    # Token cache: {token: str, expires_at: float}
    _token_cache: Optional[dict] = None

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        """
        Initialize OAuth2 handler.

        Args:
            client_id: OAuth2 client ID (defaults to SENTINEL_HUB_CLIENT_ID env var)
            client_secret: OAuth2 client secret (defaults to SENTINEL_HUB_CLIENT_SECRET env var)

        Raises:
            ValueError: If credentials not provided and env vars not set
        """
        self.client_id = client_id or os.getenv("SENTINEL_HUB_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("SENTINEL_HUB_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Sentinel Hub credentials not found. "
                "Set SENTINEL_HUB_CLIENT_ID and SENTINEL_HUB_CLIENT_SECRET env vars."
            )

    async def get_access_token(self) -> str:
        """
        Obtain access token from Sentinel Hub OAuth endpoint.

        Implements token caching: if a valid cached token exists, returns it.
        Otherwise, requests a new token and caches it.

        Returns:
            Valid OAuth2 access token string

        Raises:
            requests.exceptions.RequestException: If HTTP request fails
            ValueError: If OAuth response doesn't contain expected fields
        """
        # Check cache
        if self._token_cache and self._token_cache.get("expires_at", 0) > time.time():
            return self._token_cache["token"]

        # Request new token
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            response = requests.post(self.TOKEN_ENDPOINT, data=payload, timeout=10)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(
                f"Failed to authenticate with Sentinel Hub: {e}"
            ) from e

        data = response.json()

        if "access_token" not in data:
            raise ValueError(
                f"Invalid OAuth response: missing access_token. "
                f"Response keys: {list(data.keys())}"
            )

        token = data["access_token"]
        expires_in = data.get("expires_in", 3600)  # Default 1 hour

        # Cache token with 30-second buffer before expiration
        self._token_cache = {
            "token": token,
            "expires_at": time.time() + expires_in - 30,
        }

        return token

    def clear_cache(self) -> None:
        """Clear cached token (useful for testing)."""
        self._token_cache = None


class SentinelClient(ABC):
    """
    Abstract interface for Sentinel-2 image retrieval.
    
    Implementations will fetch satellite imagery from various sources
    (e.g., Copernicus Hub, Microsoft Planetary Computer, or other providers).
    """

    @abstractmethod
    async def get_latest_image(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        radius_m: int = 1000,
        max_cloud_coverage: float = 50.0,
    ) -> Optional[SentinelImageInfoSchema]:
        """
        Retrieve latest Sentinel-2 image for given coordinates.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            timestamp: Approximate time of event (used to find closest acquisition)
            radius_m: Search radius around coordinates in meters
            max_cloud_coverage: Maximum acceptable cloud coverage percentage

        Returns:
            SentinelImageInfoSchema with image metadata, or None if not found

        Raises:
            Exception: If API call fails (to be specified in implementations)
        """
        pass

    @abstractmethod
    async def get_ndvi_band(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
    ) -> Optional[float]:
        """
        Calculate NDVI (Normalized Difference Vegetation Index) for a point.

        NDVI = (NIR - RED) / (NIR + RED)
        Ranges from -1 (water/bare rock) to 1 (dense vegetation)

        Args:
            latitude: Target latitude
            longitude: Target longitude
            timestamp: Image acquisition time reference

        Returns:
            NDVI value between -1 and 1, or None if unavailable

        Raises:
            Exception: If calculation fails
        """
        pass

    @abstractmethod
    async def get_built_up_mask(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        radius_m: int = 1000,
    ) -> Optional[dict]:
        """
        Get built-up area mask and statistics.

        Identifies urban/industrial structures from satellite reflectance patterns.

        Args:
            latitude: Target latitude
            longitude: Target longitude
            timestamp: Image acquisition time reference
            radius_m: Analysis radius in meters

        Returns:
            Dict with:
                - built_up_percentage: float (0-100)
                - pixel_count: int
                - area_m2: float

        Returns None if analysis fails

        Raises:
            Exception: If computation fails
        """
        pass

    @abstractmethod
    async def get_spectral_indices(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
    ) -> Optional[dict]:
        """
        Calculate multiple spectral indices for fire/land-cover analysis.

        Indices may include:
        - NDVI (vegetation)
        - NDBI (built-up/urban)
        - NDMI (moisture)
        - NBR (burn ratio)
        - BSI (bare soil index)

        Args:
            latitude: Target latitude
            longitude: Target longitude
            timestamp: Image acquisition time reference

        Returns:
            Dict mapping index name to value, or None if unavailable

        Raises:
            Exception: If calculation fails
        """
        pass


class SentinelClientImpl(SentinelClient):
    """
    Concrete implementation of SentinelClient using Sentinel Hub APIs.

    Uses Copernicus Dataspace STAC API for discovery and Processing API for retrieval.

    Features:
    - Converts coordinates to 512m x 512m bounding boxes
    - Searches for cloud-free imagery within configurable time window
    - Caches images locally to minimize API calls
    - Returns RGB imagery (B04, B03, B02)
    """

    # Sentinel Hub endpoints
    STAC_API_URL = "https://stac.dataspace.copernicus.eu/api/v1"
    PROCESSING_API_URL = "https://eodata.dataspace.copernicus.eu/api/v1"

    # Image cache directory
    CACHE_DIR = Path(__file__).parent.parent / ".sentinel_cache"

    # Configuration
    DEFAULT_TIME_WINDOW_DAYS = 5  # Search ±5 days around event
    DEFAULT_BOX_SIZE_M = 512  # 512m x 512m box
    DEFAULT_IMAGE_SIZE_PX = 512  # 512x512 pixels
    DEFAULT_MAX_CLOUD_COVERAGE = 50.0  # Accept up to 50% cloud
    COLLECTION_ID = "sentinel-2"  # L2A collection
    BANDS_RGB = ["B04", "B03", "B02"]  # Red, Green, Blue

    def __init__(self, auth: Optional[SentinelHubAuth] = None):
        """
        Initialize Sentinel client.

        Args:
            auth: SentinelHubAuth instance for OAuth2. If None, creates new instance.
        """
        self.auth = auth or SentinelHubAuth()
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ========================
    # Coordinate / BBox Helper
    # ========================

    @staticmethod
    def _latlon_to_bbox(
        latitude: float,
        longitude: float,
        box_size_m: int = DEFAULT_BOX_SIZE_M,
    ) -> dict:
        """
        Convert lat/lon point to bounding box (meters x meters).

        Approximation: at equator, 1° ≈ 111 km
        Uses simple conversion; for production, use pyproj for accuracy.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            box_size_m: Box size in meters (e.g., 512)

        Returns:
            Dict with keys: north, south, east, west (in degrees)
        """
        # Approximate degrees per meter (varies with latitude)
        # At equator: ~0.000009 degrees/meter
        # Simplified: assume ~110km per degree
        degrees_per_meter = 1.0 / 111000.0
        delta = box_size_m * degrees_per_meter

        return {
            "north": latitude + delta,
            "south": latitude - delta,
            "east": longitude + delta,
            "west": longitude - delta,
        }

    @staticmethod
    def _cache_key(
        latitude: float,
        longitude: float,
        timestamp: datetime,
    ) -> str:
        """
        Generate deterministic cache key from coordinates and date.

        Args:
            latitude: Latitude
            longitude: Longitude
            timestamp: Event timestamp

        Returns:
            SHA256 hash as cache key
        """
        # Use date (not time) as granularity
        date_str = timestamp.strftime("%Y-%m-%d")
        key_input = f"{latitude:.4f}_{longitude:.4f}_{date_str}"
        return hashlib.sha256(key_input.encode()).hexdigest()[:16]

    def _get_cached_image_path(self, cache_key: str) -> Path:
        """Get path to cached image file."""
        return self.CACHE_DIR / f"{cache_key}.json"

    def _read_from_cache(self, cache_key: str) -> Optional[SentinelImageInfoSchema]:
        """
        Attempt to read image info from local cache.

        Returns:
            Parsed SentinelImageInfoSchema or None if not cached
        """
        cache_file = self._get_cached_image_path(cache_key)
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            return SentinelImageInfoSchema(**data)
        except (json.JSONDecodeError, ValueError):
            # Cache corrupted, remove it
            cache_file.unlink()
            return None

    def _write_to_cache(
        self, cache_key: str, image_info: SentinelImageInfoSchema
    ) -> None:
        """Write image info to local cache."""
        cache_file = self._get_cached_image_path(cache_key)
        try:
            with open(cache_file, "w") as f:
                json.dump(image_info.dict(), f, default=str)
        except Exception as e:
            print(f"Warning: Could not write cache file {cache_file}: {e}")

    # ========================
    # STAC Search & Discovery
    # ========================

    async def _search_stac_for_image(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        max_cloud_coverage: float,
    ) -> Optional[dict]:
        """
        Search STAC API for available Sentinel-2 L2A images.

        Args:
            latitude: Center latitude
            longitude: Center longitude
            timestamp: Event timestamp
            max_cloud_coverage: Max cloud % to accept

        Returns:
            STAC item metadata (first result) or None if no suitable image found
        """
        bbox = self._latlon_to_bbox(latitude, longitude)
        start_date = (timestamp - timedelta(days=self.DEFAULT_TIME_WINDOW_DAYS)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        end_date = (timestamp + timedelta(days=self.DEFAULT_TIME_WINDOW_DAYS)).strftime(
            "%Y-%m-%dT23:59:59Z"
        )

        # STAC search request (POST Body)
        search_request = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [bbox["west"], bbox["south"]],
                                [bbox["east"], bbox["south"]],
                                [bbox["east"], bbox["north"]],
                                [bbox["west"], bbox["north"]],
                                [bbox["west"], bbox["south"]],
                            ]
                        ],
                    },
                }
            ],
            "filter": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "start_datetime": start_date,
                            "end_datetime": end_date,
                            "eo:cloud_cover": {"lte": max_cloud_coverage},
                            "collection": self.COLLECTION_ID,
                        },
                    }
                ],
            },
            "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            "limit": 5,  # Get top 5 candidates sorted by cloud cover
        }

        token = await self.auth.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                f"{self.STAC_API_URL}/search",
                json=search_request,
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"STAC search failed: {e}")
            return None

        data = response.json()

        # Return first (best) result
        if data.get("features"):
            return data["features"][0]

        return None

    # ========================
    # Image Retrieval
    # ========================

    async def get_latest_image(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        radius_m: int = 1000,
        max_cloud_coverage: float = 50.0,
    ) -> Optional[SentinelImageInfoSchema]:
        """
        Retrieve latest Sentinel-2 image for given coordinates.

        Pipeline:
        1. Check local cache
        2. Search STAC API for suitable image
        3. Retrieve RGB image data
        4. Cache result
        5. Return metadata

        Args:
            latitude: Target latitude
            longitude: Target longitude
            timestamp: Approximate time of event
            radius_m: Search radius (note: currently fixed at 512m for MVP)
            max_cloud_coverage: Maximum acceptable cloud coverage percentage

        Returns:
            SentinelImageInfoSchema with image URL and metadata, or None

        Raises:
            Exception: Logged but handled gracefully
        """
        cache_key = self._cache_key(latitude, longitude, timestamp)

        # Check cache first
        cached = self._read_from_cache(cache_key)
        if cached:
            print(f"Image found in cache: {cache_key}")
            return cached

        # Search STAC for available image
        stac_item = await self._search_stac_for_image(
            latitude, longitude, timestamp, max_cloud_coverage
        )
        if not stac_item:
            print(f"No suitable Sentinel-2 image found for {latitude}, {longitude}")
            return None

        # Extract metadata from STAC item
        properties = stac_item.get("properties", {})
        assets = stac_item.get("assets", {})
        image_id = stac_item.get("id", "unknown")
        cloud_coverage = properties.get("eo:cloud_cover", 0)

        # Extract acquisition date
        datetime_str = properties.get("datetime", timestamp.isoformat())
        try:
            acquisition_date = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            acquisition_date = timestamp

        # Get bounding box info
        bbox_data = self._latlon_to_bbox(latitude, longitude)
        
        # Build image URL (simplified - would use Processing API in production)
        image_url = self._build_image_url(image_id, latitude, longitude)

        # Get available bands
        bands_available = list(assets.keys())
        if not bands_available:
            bands_available = self.BANDS_RGB

        # Create response
        image_info = SentinelImageInfoSchema(
            image_url=image_url,
            acquisition_date=acquisition_date,
            cloud_coverage=float(cloud_coverage),
            bands_available=bands_available,
            resolution_m=10,  # Sentinel-2 standard 10m resolution for RGB
        )

        # Cache result
        self._write_to_cache(cache_key, image_info)

        return image_info

    def _build_image_url(
        self, image_id: str, latitude: float, longitude: float
    ) -> str:
        """
        Build image URL for Processing API request.

        Note: In production, this would return a signed URL or proxy endpoint.
        For MVP, returns a reference URL.

        Args:
            image_id: STAC item ID
            latitude: Latitude
            longitude: Longitude

        Returns:
            URL string (would be served by backend to avoid exposing credentials)
        """
        # Example: In production, would proxy through FastAPI endpoint
        # /api/satellite/image/{cache_key}/rgb.png
        # For now, return API reference
        return f"s3://copernicus-tiles/sentinel-2/{image_id}/TCI.tif"

    # ========================
    # Spectral Indices
    # ========================

    async def get_ndvi_band(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
    ) -> Optional[float]:
        """Placeholder: Calculate NDVI from Sentinel-2 NIR and RED bands."""
        # TODO: Implement NDVI calculation using Processing API
        # NDVI = (B08 - B04) / (B08 + B04)
        return None

    async def get_built_up_mask(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
        radius_m: int = 1000,
    ) -> Optional[dict]:
        """Placeholder: Detect built-up areas using NDBI."""
        # TODO: Implement built-up detection using NDBI = (B11 - B04) / (B11 + B04)
        return None

    async def get_spectral_indices(
        self,
        latitude: float,
        longitude: float,
        timestamp: datetime,
    ) -> Optional[dict]:
        """Placeholder: Calculate multiple spectral indices."""
        # TODO: Implement multi-index calculation
        return None
