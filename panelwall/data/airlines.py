"""ICAO 3-letter airline code (from the callsign) -> (IATA 2-letter, display name).

Callsigns look like 'JBU1287'. The first three letters are the ICAO operator
code; the rest is the flight number. Airlines seen at BOS, plus common
overflight carriers. Unknown codes fall back to the raw callsign.
"""

AIRLINES: dict[str, tuple[str, str]] = {
    "JBU": ("B6", "JETBLUE"),
    "DAL": ("DL", "DELTA"),
    "AAL": ("AA", "AMERICAN"),
    "UAL": ("UA", "UNITED"),
    "SWA": ("WN", "SOUTHWEST"),
    "ASA": ("AS", "ALASKA"),
    "NKS": ("NK", "SPIRIT"),
    "FFT": ("F9", "FRONTIER"),
    "SCX": ("SY", "SUN COUNTRY"),
    "CJC": ("OH", "PSA"),          # American Eagle
    "PDT": ("PT", "PIEDMONT"),     # American Eagle
    "RPA": ("YX", "REPUBLIC"),
    "ENY": ("MQ", "ENVOY"),
    "EDV": ("9E", "ENDEAVOR"),
    "SKW": ("OO", "SKYWEST"),
    "ASH": ("YV", "MESA"),
    "GJS": ("G7", "GOJET"),
    "JIA": ("OH", "PSA"),
    "ACA": ("AC", "AIR CANADA"),
    "JZA": ("QK", "JAZZ"),
    "POE": ("PD", "PORTER"),
    "WJA": ("WS", "WESTJET"),
    "EIN": ("EI", "AER LINGUS"),
    "BAW": ("BA", "BRITISH AIRWAYS"),
    "VIR": ("VS", "VIRGIN ATLANTIC"),
    "DLH": ("LH", "LUFTHANSA"),
    "SWR": ("LX", "SWISS"),
    "AFR": ("AF", "AIR FRANCE"),
    "KLM": ("KL", "KLM"),
    "IBE": ("IB", "IBERIA"),
    "TAP": ("TP", "TAP PORTUGAL"),
    "AZA": ("AZ", "ITA AIRWAYS"),
    "ICE": ("FI", "ICELANDAIR"),
    "SAS": ("SK", "SAS"),
    "NAX": ("DY", "NORWEGIAN"),
    "UAE": ("EK", "EMIRATES"),
    "QTR": ("QR", "QATAR"),
    "ETH": ("ET", "ETHIOPIAN"),
    "THY": ("TK", "TURKISH"),
    "ELY": ("LY", "EL AL"),
    "CPA": ("CX", "CATHAY"),
    "JAL": ("JL", "JAPAN AIRLINES"),
    "HAL": ("HA", "HAWAIIAN"),
    "CMP": ("CM", "COPA"),
    "AVA": ("AV", "AVIANCA"),
    "LAN": ("LA", "LATAM"),
    "AMX": ("AM", "AEROMEXICO"),
    "CAY": ("KX", "CAYMAN"),
    "FDX": ("FX", "FEDEX"),
    "UPS": ("5X", "UPS"),
    "ATN": ("8C", "ATI"),
    "GTI": ("5Y", "ATLAS"),
    "KAP": ("9K", "CAPE AIR"),
    "TSC": ("TS", "AIR TRANSAT"),
    "BHS": ("UP", "BAHAMASAIR"),
    "RYR": ("FR", "RYANAIR"),
    "EJU": ("U2", "EASYJET"),
}


def parse_callsign(callsign: str | None) -> tuple[str, str, str]:
    """'JBU1287 ' -> ('B6', 'JETBLUE', '1287'). Unknown -> ('', '', 'JBU1287')."""
    cs = (callsign or "").strip().upper()
    if len(cs) >= 4 and cs[:3].isalpha() and cs[:3] in AIRLINES:
        iata, name = AIRLINES[cs[:3]]
        return iata, name, cs[3:]
    return "", "", cs


def short_flight(callsign: str | None) -> str:
    """Display form: 'B6 1287' when the airline is known, else the raw callsign."""
    iata, _, num = parse_callsign(callsign)
    return f"{iata} {num}" if iata else num
