import requests
from typing import Dict, List, Tuple
import polyline
import time

# FREE geocoding service from OpenStreetMap
NOMINATIM_URL = "https://nominatim.openstreetmap.org"

# FREE routing service
OSRM_URL = "https://router.project-osrm.org"

# User agent required by Nominatim
HEADERS = {
    'User-Agent': 'HFC-Transport/1.0 (contact@howfar.ng)'
}

def get_route(origin: Tuple[float, float], destination: Tuple[float, float]) -> Dict:
    """
    Get route from origin to destination using FREE OSRM routing service.
    
    Args:
        origin: (latitude, longitude)
        destination: (latitude, longitude)
    
    Returns:
        {
            'polyline': str,
            'duration': int (seconds),
            'distance': float (kilometers),
            'geometry': List[List[float]]  # [[lat, lng], ...]
        }
    """
    try:
        # OSRM uses lng,lat order (opposite of most services)
        url = f"{OSRM_URL}/route/v1/driving/{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        
        params = {
            'overview': 'full',
            'geometries': 'polyline',
            'steps': 'true',
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data['code'] != 'Ok':
            return None
        
        route = data['routes'][0]
        
        # Decode polyline to get coordinates
        coords = polyline.decode(route['geometry'])
        
        return {
            'polyline': route['geometry'],
            'duration': int(route['duration']),  # seconds
            'distance': route['distance'] / 1000,  # convert m to km
            'geometry': [[lat, lng] for lat, lng in coords],  # Leaflet format
        }
    except Exception as e:
        print(f"Error getting route: {e}")
        return None

def geocode_address(address: str) -> Dict:
    """
    Convert address to lat/lng using FREE Nominatim service.
    
    Args:
        address: Address string
    
    Returns:
        {
            'latitude': float,
            'longitude': float,
            'formatted_address': str,
        }
    """
    try:
        url = f"{NOMINATIM_URL}/search"
        
        params = {
            'q': address,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1,
        }
        
        # Nominatim requires min 1 second between requests
        time.sleep(1)
        
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        results = response.json()
        
        if not results:
            return None
        
        result = results[0]
        
        return {
            'latitude': float(result['lat']),
            'longitude': float(result['lon']),
            'formatted_address': result['display_name'],
        }
    except Exception as e:
        print(f"Error geocoding: {e}")
        return None

def reverse_geocode(latitude: float, longitude: float) -> str:
    """
    Convert lat/lng to address using FREE Nominatim service.
    
    Args:
        latitude: Latitude
        longitude: Longitude
    
    Returns:
        str: Formatted address
    """
    try:
        url = f"{NOMINATIM_URL}/reverse"
        
        params = {
            'lat': latitude,
            'lon': longitude,
            'format': 'json',
            'addressdetails': 1,
        }
        
        # Nominatim requires min 1 second between requests
        time.sleep(1)
        
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        return data.get('display_name', 'Unknown location')
    except Exception as e:
        print(f"Error reverse geocoding: {e}")
        return 'Unknown location'

def autocomplete_address(input_text: str, location: Tuple[float, float] = None) -> List[Dict]:
    """
    Get address suggestions using FREE Photon autocomplete service.
    
    Args:
        input_text: Search query
        location: (latitude, longitude) for biasing results
    
    Returns:
        List of suggestions with place info
    """
    try:
        # Photon - FREE geocoding autocomplete by Komoot
        url = "https://photon.komoot.io/api/"
        
        params = {
            'q': input_text,
            'limit': 5,
        }
        
        # Bias results to location if provided
        if location:
            params['lat'] = location[0]
            params['lon'] = location[1]
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        suggestions = []
        for feature in data.get('features', []):
            props = feature['properties']
            coords = feature['geometry']['coordinates']  # [lng, lat]
            
            suggestions.append({
                'place_id': feature.get('properties', {}).get('osm_id'),
                'description': props.get('name', ''),
                'main_text': props.get('name', ''),
                'secondary_text': ', '.join(filter(None, [
                    props.get('street'),
                    props.get('city'),
                    props.get('country')
                ])),
                'latitude': coords[1],
                'longitude': coords[0],
            })
        
        return suggestions
    except Exception as e:
        print(f"Error in autocomplete: {e}")
        return []

def find_nearby_drivers(latitude: float, longitude: float, radius_km: float = 5.0) -> List:
    """
    Find available drivers within radius using simple distance calculation.
    
    Args:
        latitude: Search center latitude
        longitude: Search center longitude
        radius_km: Search radius in kilometers
    
    Returns:
        List of nearby drivers with distance
    """
    from rides.models import DriverLocation
    from math import radians, cos, sin, asin, sqrt
    
    def haversine(lon1, lat1, lon2, lat2):
        """Calculate distance between two points in km"""
        lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        km = 6371 * c
        return km
    
    # Get all active drivers
    drivers = DriverLocation.objects.filter(
        is_active=True,
        driver__role='driver',
    ).select_related('driver')
    
    # Filter by distance
    nearby = []
    for driver_loc in drivers:
        distance = haversine(
            driver_loc.longitude,
            driver_loc.latitude,
            longitude,
            latitude
        )
        
        if distance <= radius_km:
            nearby.append({
                'driver_id': str(driver_loc.driver.id),
                'driver_name': driver_loc.driver.full_name,
                'latitude': driver_loc.latitude,
                'longitude': driver_loc.longitude,
                'distance': round(distance, 2),
                'rating': getattr(driver_loc.driver, 'average_rating', 5.0),
            })
    
    # Sort by distance
    nearby.sort(key=lambda x: x['distance'])
    return nearby
