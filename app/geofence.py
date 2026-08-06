from math import asin, cos, radians, sin, sqrt


EARTH_RADIUS_M = 6_371_000


def distance_metres(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Return great-circle distance using the Haversine formula."""
    lat_delta = radians(latitude_b - latitude_a)
    lon_delta = radians(longitude_b - longitude_a)
    a = sin(lat_delta / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(lon_delta / 2) ** 2
    return EARTH_RADIUS_M * 2 * asin(sqrt(a))
