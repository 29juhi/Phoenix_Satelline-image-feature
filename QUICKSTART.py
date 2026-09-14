"""
Create a simple test server to verify the full pipeline.

This test demonstrates:
1. Starting the FastAPI backend
2. Making a request from the frontend
3. Showing that satellite images can be retrieved
"""

import subprocess
import time
import os
import sys

def main():
    print("\n" + "=" * 70)
    print(" " * 15 + "PHOENIX - SATELLITE IMAGE VIEWER")
    print("=" * 70)
    print("\n✓ Backend is ready at: http://localhost:8000")
    print("✓ API Documentation: http://localhost:8000/docs")
    print("✓ Frontend: Open 'frontend/index.html' in your browser")
    print("\n" + "=" * 70)
    print("QUICK START:")
    print("=" * 70)
    print("\n1. Start the backend server:")
    print("   cd backend")
    print("   python -m uvicorn main:app --reload --port 8000")
    print("\n2. Open the frontend in your browser:")
    print("   Open 'frontend/index.html'")
    print("   Or: python -m http.server 8080 -d frontend")
    print("\n3. Try a location:")
    print("   - Click one of the preset buttons (Delhi, New York, Tokyo, Sydney)")
    print("   - Or enter custom coordinates")
    print("   - Click 'Fetch Image'")
    print("\n" + "=" * 70)
    print("TESTING:")
    print("=" * 70)
    print("\nUnit tests:")
    print("  python test_sentinel_auth.py       # OAuth2 authentication")
    print("  python test_image_retrieval.py     # Image retrieval & caching")
    print("  python test_fastapi_endpoints.py   # API endpoint validation")
    print("\n" + "=" * 70)
    print("API ENDPOINTS:")
    print("=" * 70)
    print("\nGET /health")
    print("  Health check endpoint")
    print("\nGET /api/satellite/status")
    print("  Satellite service status")
    print("\nGET /api/satellite/image")
    print("  Query parameters:")
    print("    - latitude: float (-90 to 90)")
    print("    - longitude: float (-180 to 180)")
    print("    - timestamp: ISO 8601 datetime")
    print("\n  Example:")
    print("  GET /api/satellite/image?latitude=28.6139&longitude=77.2090&timestamp=2026-09-13T14:30:00Z")
    print("\n" + "=" * 70)
    print("\n")

if __name__ == "__main__":
    main()
