"""
Example usage of OSM facility lookup for Phoenix fire confirmation.

Demonstrates:
- Finding nearby industrial facilities
- Analyzing land use categories
- Getting comprehensive OSM context
- Using results for fire confirmation
"""

import asyncio
from backend.satellite.osm_client import OSMClientImpl


async def main():
    """Demonstrate OSM client usage."""
    
    # Initialize OSM client
    osm = OSMClientImpl()
    
    # Example 1: Find nearby facilities around Delhi
    print("=" * 80)
    print("EXAMPLE 1: Finding Industrial Facilities")
    print("=" * 80)
    
    delhi_lat, delhi_lon = 28.6139, 77.2090
    print(f"\nSearching for facilities near Delhi ({delhi_lat}, {delhi_lon})...")
    print("Search radius: 2000m")
    
    facilities = await osm.get_nearby_facilities(
        delhi_lat, delhi_lon, radius_m=2000
    )
    
    print(f"\nFound {len(facilities)} facilities:")
    for i, facility in enumerate(facilities[:5], 1):  # Show top 5
        print(f"\n  {i}. {facility['name']}")
        print(f"     Type: {facility['type']}")
        print(f"     Distance: {facility['distance_m']:.0f}m")
        print(f"     Lat/Lon: {facility['latitude']:.4f}, {facility['longitude']:.4f}")
    
    # Example 2: Find nearest industrial facility
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Finding Nearest Industrial Facility")
    print("=" * 80)
    
    nearest = await osm.get_nearest_facility(
        delhi_lat, delhi_lon, facility_type="industrial", max_distance_m=5000
    )
    
    if nearest:
        print(f"\nNearest industrial facility:")
        print(f"  Name: {nearest['name']}")
        print(f"  Distance: {nearest['distance_m']:.0f}m")
        print(f"  Type: {nearest['type']}")
    else:
        print("\nNo industrial facility found within 5km")
    
    # Example 3: Land use analysis
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Land Use Analysis")
    print("=" * 80)
    
    print(f"\nAnalyzing land use around Delhi...")
    land_use = await osm.get_land_use_categories(
        delhi_lat, delhi_lon, radius_m=2000
    )
    
    if land_use:
        print(f"\nLand use categories found:")
        for category, count in sorted(
            land_use.items(), key=lambda x: x[1], reverse=True
        ):
            print(f"  {category}: {count} areas")
    else:
        print("\nNo land use data available")
    
    # Example 4: Full OSM context (parallel queries)
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Full OSM Context (Parallel Queries)")
    print("=" * 80)
    
    print(f"\nFetching comprehensive OSM context...")
    context = await osm.get_full_osm_context(
        delhi_lat, delhi_lon, radius_m=2000
    )
    
    print(f"\nOSM Context Summary:")
    print(f"  Nearby facilities: {len(context.nearby_facilities)}")
    print(f"  Land use categories: {len(context.land_use_categories)}")
    if context.distance_to_nearest_facility_m:
        print(f"  Nearest facility: {context.distance_to_nearest_facility_m:.0f}m")
    else:
        print(f"  Nearest facility: Not found")
    
    # Example 5: Different locations
    print("\n" + "=" * 80)
    print("EXAMPLE 5: Multi-Location Analysis")
    print("=" * 80)
    
    locations = {
        "New York (refinery area)": (40.6331, -74.0996),
        "Houston (refinery area)": (29.7589, -95.3677),
        "Chennai (port area)": (13.0827, 80.2707),
    }
    
    for name, (lat, lon) in locations.items():
        print(f"\n  {name}: ({lat}, {lon})")
        context = await osm.get_full_osm_context(lat, lon, radius_m=1500)
        print(f"    - Facilities: {len(context.nearby_facilities)}")
        print(f"    - Land use types: {len(context.land_use_categories)}")
    
    # Example 6: Fire confirmation use case
    print("\n" + "=" * 80)
    print("EXAMPLE 6: Fire Confirmation Context")
    print("=" * 80)
    
    hotspot_lat, hotspot_lon = 28.6139, 77.2090
    print(f"\n🔥 Hotspot detected at ({hotspot_lat}, {hotspot_lon})")
    print(f"   Predicted class: Industrial Fire")
    print(f"   Confidence: 0.85")
    
    print(f"\n📍 Checking nearby industrial features (500m radius)...")
    facilities = await osm.get_nearby_facilities(
        hotspot_lat, hotspot_lon, radius_m=500, 
        facility_types=["industrial", "refinery", "factory", "power_plant"]
    )
    
    if facilities:
        print(f"✅ Found {len(facilities)} industrial facility(ies):")
        for f in facilities[:3]:
            print(f"   • {f['name']} ({f['distance_m']:.0f}m away)")
        print(f"\n✅ CONSISTENT: Industrial fire prediction matches nearby facilities")
    else:
        print(f"⚠️  No industrial facilities found in 500m radius")
        print(f"❓ UNCERTAIN: Cannot confirm industrial fire without facility context")


if __name__ == "__main__":
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 78 + "║")
    print("║" + "  Phoenix Feature 12: OSM Facility Lookup Examples".center(78) + "║")
    print("║" + " " * 78 + "║")
    print("╚" + "=" * 78 + "╝")
    
    asyncio.run(main())
    
    print("\n" + "=" * 80)
    print("✅ OSM examples complete!")
    print("=" * 80 + "\n")
