"""ICAO aircraft type designator -> short display name."""

TYPES: dict[str, str] = {
    "A19N": "A319NEO", "A20N": "A320NEO", "A21N": "A321NEO",
    "A318": "A318", "A319": "A319", "A320": "A320", "A321": "A321",
    "A332": "A330-200", "A333": "A330-300", "A339": "A330NEO",
    "A342": "A340", "A343": "A340", "A346": "A340-600",
    "A359": "A350-900", "A35K": "A350-1000", "A388": "A380",
    "A306": "A300", "A310": "A310",
    "B712": "717", "B722": "727",
    "B733": "737-300", "B734": "737-400", "B735": "737-500",
    "B736": "737-600", "B737": "737-700", "B738": "737-800", "B739": "737-900",
    "B37M": "737 MAX 7", "B38M": "737 MAX 8", "B39M": "737 MAX 9", "B3XM": "737 MAX 10",
    "B741": "747-100", "B742": "747-200", "B744": "747-400", "B748": "747-8",
    "B752": "757-200", "B753": "757-300",
    "B762": "767-200", "B763": "767-300", "B764": "767-400",
    "B772": "777-200", "B773": "777-300", "B77L": "777-200LR", "B77W": "777-300ER",
    "B788": "787-8", "B789": "787-9", "B78X": "787-10",
    "E170": "E170", "E75L": "E175", "E75S": "E175", "E190": "E190", "E195": "E195",
    "E290": "E190-E2", "E295": "E195-E2",
    "BCS1": "A220-100", "BCS3": "A220-300",
    "CRJ2": "CRJ-200", "CRJ7": "CRJ-700", "CRJ9": "CRJ-900", "CRJX": "CRJ-1000",
    "DH8D": "DASH 8", "DH8C": "DASH 8", "AT72": "ATR 72", "AT76": "ATR 72",
    "MD11": "MD-11", "MD82": "MD-82", "MD83": "MD-83", "MD88": "MD-88", "MD90": "MD-90",
    "C402": "CESSNA 402", "C208": "CARAVAN", "C172": "CESSNA 172",
    "PC12": "PC-12", "BE20": "KING AIR", "BE9L": "KING AIR", "B350": "KINGAIR350",
    "C25A": "CJ2", "C25B": "CJ3", "C56X": "CIT XLS", "C680": "SOVEREIGN", "C68A": "LATITUDE",
    "C700": "LONGITUDE", "C750": "CITATION X",
    "CL30": "CHALLENGER", "CL35": "CHALLENGER", "CL60": "CHALLENGER",
    "GLF4": "GULFSTREAM", "GLF5": "GULFSTREAM", "GLF6": "G650", "GL5T": "GLOBAL", "GL7T": "GLBL 7500",
    "GLEX": "GLOBAL", "E55P": "PHENOM 300", "E50P": "PHENOM 100", "LJ45": "LEARJET", "LJ60": "LEARJET",
    "HDJT": "HONDAJET", "PRM1": "PREMIER", "FA7X": "FALCON 7X", "F2TH": "FALCON2000", "FA50": "FALCON 50",
    "SR22": "SR22", "SR20": "SR20", "S22T": "SR22",
    "PA28": "PIPER", "P28A": "ARCHER", "P28R": "ARROW", "P28T": "PIPER", "PA32": "PIPER SIX",
    "PA34": "SENECA", "PA44": "SEMINOLE", "PA46": "MALIBU", "P46T": "MERIDIAN", "PA31": "NAVAJO",
    "C150": "CESSNA 150", "C152": "CESSNA 152", "C177": "CARDINAL", "C182": "CESSNA 182", "C206": "CESSNA 206",
    "C210": "CESSNA 210", "C310": "CESSNA 310", "C340": "CESSNA 340", "C414": "CESSNA 414", "C421": "CESSNA 421",
    "BE36": "BONANZA", "BE33": "BONANZA", "BE35": "BONANZA", "BE58": "BARON", "BE55": "BARON", "BE76": "DUCHESS",
    "M20P": "MOONEY", "M20T": "MOONEY", "DA40": "DIAMOND", "DA42": "DA42", "DA62": "DA62",
    "TBM7": "TBM 700", "TBM8": "TBM 850", "TBM9": "TBM 900", "PC24": "PC-24", "EPIC": "EPIC E1000",
    "COL4": "COLUMBIA", "AC11": "COMMANDER", "RV10": "VANS RV-10", "RV7": "VANS RV-7", "GA8": "AIRVAN",
    "R44": "R44 HELI", "R66": "R66 HELI", "EC35": "EC135", "EC45": "EC145", "A109": "A109",
    "S76": "S-76", "B06": "BELL 206", "B407": "BELL 407", "AS50": "AS350", "H60": "BLACKHAWK",
    "GLID": "GLIDER", "BALL": "BALLOON", "UAV": "DRONE",
}

HEAVIES = {"A332", "A333", "A339", "A342", "A343", "A346", "A359", "A35K", "A388",
           "B744", "B748", "B762", "B763", "B764", "B772", "B773", "B77L", "B77W",
           "B788", "B789", "B78X", "MD11", "A306", "A310"}


def type_name(icao: str | None) -> str:
    if not icao:
        return "UNKNOWN"
    return TYPES.get(icao.upper(), icao.upper())
