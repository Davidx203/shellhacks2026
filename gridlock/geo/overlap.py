from math import radians, cos, sin, asin, sqrt



def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8 # Earth radius in miles
    dlat , dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))


print(haversine_miles(25.7617, -80.1918, 25.9000, -80.1918))
