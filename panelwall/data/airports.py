"""IATA airport code -> (lat, lon). Used only to place the route progress dot.

Two decimals is plenty: the dot moves in 1/40ths of a 40 px line. Airports
missing from this table make the dot sit in the middle - nothing else breaks.
"""

import math

AIRPORTS: dict[str, tuple[float, float]] = {
    # New England / Northeast
    "BOS": (42.36, -71.01), "PVD": (41.72, -71.43), "BDL": (41.94, -72.68), "MHT": (42.93, -71.44),
    "PWM": (43.65, -70.31), "BGR": (44.81, -68.83), "BTV": (44.47, -73.15), "ALB": (42.75, -73.80),
    "ACK": (41.25, -70.06), "MVY": (41.39, -70.61), "HYA": (41.67, -70.28), "LEB": (43.63, -72.30),
    "ORH": (42.27, -71.88), "SYR": (43.11, -76.11), "ROC": (43.12, -77.67), "BUF": (42.94, -78.73),
    "JFK": (40.64, -73.78), "LGA": (40.78, -73.87), "EWR": (40.69, -74.17), "HPN": (41.07, -73.71),
    "ISP": (40.80, -73.10), "SWF": (41.50, -74.10), "ACY": (39.46, -74.58), "PHL": (39.87, -75.24),
    "BWI": (39.18, -76.67), "DCA": (38.85, -77.04), "IAD": (38.95, -77.46), "RIC": (37.51, -77.32),
    "ORF": (36.89, -76.20), "PIT": (40.49, -80.23),
    # Southeast
    "CLT": (35.21, -80.94), "RDU": (35.88, -78.79), "GSO": (36.10, -79.94), "GSP": (34.90, -82.22),
    "ILM": (34.27, -77.90), "MYR": (33.68, -78.93), "CHS": (32.90, -80.04), "SAV": (32.13, -81.20),
    "ATL": (33.64, -84.43), "BNA": (36.12, -86.68), "MEM": (35.04, -89.98), "SDF": (38.17, -85.74),
    "JAX": (30.49, -81.69), "MCO": (28.43, -81.31), "TPA": (27.98, -82.53), "RSW": (26.54, -81.76),
    "PBI": (26.68, -80.10), "FLL": (26.07, -80.15), "MIA": (25.79, -80.29), "MSY": (29.99, -90.26),
    # Midwest
    "ORD": (41.97, -87.91), "MDW": (41.79, -87.75), "MKE": (42.95, -87.90), "MSP": (44.88, -93.22),
    "DTW": (42.21, -83.35), "CLE": (41.41, -81.85), "CMH": (39.99, -82.89), "CVG": (39.05, -84.67),
    "IND": (39.72, -86.29), "STL": (38.75, -90.37), "MCI": (39.30, -94.71), "OMA": (41.30, -95.89),
    # Texas / Mountain / Southwest
    "DFW": (32.90, -97.04), "DAL": (32.85, -96.85), "IAH": (29.98, -95.34), "HOU": (29.65, -95.28),
    "AUS": (30.19, -97.67), "SAT": (29.53, -98.47), "ELP": (31.81, -106.38), "OKC": (35.39, -97.60),
    "TUL": (36.20, -95.89), "DEN": (39.86, -104.67), "SLC": (40.79, -111.98), "ABQ": (35.04, -106.61),
    "PHX": (33.43, -112.01), "TUS": (32.12, -110.94), "LAS": (36.08, -115.15), "RNO": (39.50, -119.77),
    "BOI": (43.56, -116.22), "PSP": (33.83, -116.51),
    # West coast / Alaska / Hawaii
    "LAX": (33.94, -118.41), "SFO": (37.62, -122.38), "OAK": (37.72, -122.22), "SJC": (37.36, -121.93),
    "SAN": (32.73, -117.19), "SNA": (33.68, -117.87), "BUR": (34.20, -118.36), "ONT": (34.06, -117.60),
    "SMF": (38.70, -121.59), "SEA": (47.45, -122.31), "PDX": (45.59, -122.60), "ANC": (61.17, -149.98),
    "HNL": (21.32, -157.92),
    # Canada
    "YYZ": (43.68, -79.63), "YUL": (45.47, -73.74), "YOW": (45.32, -75.67), "YHZ": (44.88, -63.51),
    "YVR": (49.19, -123.18),
    # Caribbean / Latin America
    "SJU": (18.44, -66.00), "STT": (18.34, -64.97), "NAS": (25.04, -77.47), "BDA": (32.36, -64.68),
    "MBJ": (18.50, -77.91), "PUJ": (18.57, -68.36), "CUN": (21.04, -86.87), "MEX": (19.44, -99.07),
    "PTY": (9.07, -79.38), "BOG": (4.70, -74.15), "LIM": (-12.02, -77.11), "GRU": (-23.43, -46.47),
    "SCL": (-33.39, -70.79), "BGI": (13.07, -59.49),
    # Europe / Middle East / Asia
    "DUB": (53.42, -6.27), "SNN": (52.70, -8.92), "KEF": (63.99, -22.61), "LHR": (51.47, -0.46),
    "LGW": (51.15, -0.19), "CDG": (49.01, 2.55), "AMS": (52.31, 4.76), "FRA": (50.03, 8.57),
    "MUC": (48.35, 11.79), "ZRH": (47.46, 8.55), "MAD": (40.47, -3.56), "BCN": (41.30, 2.08),
    "LIS": (38.77, -9.13), "FCO": (41.80, 12.24), "MXP": (45.63, 8.72), "CPH": (55.62, 12.65),
    "ARN": (59.65, 17.92), "OSL": (60.19, 11.10), "IST": (41.26, 28.74), "DOH": (25.27, 51.61),
    "DXB": (25.25, 55.36), "TLV": (32.01, 34.89), "HKG": (22.31, 113.91), "NRT": (35.77, 140.39),
    "ADD": (8.98, 38.80),
}


def great_circle_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def route_progress(origin: str, dest: str, lat: float | None, lon: float | None) -> float | None:
    """Fraction (0..1) of the origin->dest great-circle already flown, judged by
    where the aircraft is now. None if either airport is unknown or no position."""
    o, d = AIRPORTS.get(origin.upper()), AIRPORTS.get(dest.upper())
    if o is None or d is None or lat is None or lon is None:
        return None
    flown = great_circle_nm(o[0], o[1], lat, lon)
    left = great_circle_nm(lat, lon, d[0], d[1])
    if flown + left <= 0:
        return None
    return max(0.0, min(1.0, flown / (flown + left)))
