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

# Manufacturer + model, as the FlightWall shows it ("Boeing 737-700"). Falls back to the short name.
LONG_TYPES: dict[str, str] = {
    "A19N": "Airbus A319neo", "A20N": "Airbus A320neo", "A21N": "Airbus A321neo",
    "A318": "Airbus A318", "A319": "Airbus A319", "A320": "Airbus A320", "A321": "Airbus A321",
    "A332": "Airbus A330-200", "A333": "Airbus A330-300", "A339": "Airbus A330-900neo",
    "A342": "Airbus A340-200", "A343": "Airbus A340-300", "A346": "Airbus A340-600",
    "A359": "Airbus A350-900", "A35K": "Airbus A350-1000", "A388": "Airbus A380-800",
    "A306": "Airbus A300-600", "A310": "Airbus A310",
    "B712": "Boeing 717-200", "B722": "Boeing 727-200",
    "B733": "Boeing 737-300", "B734": "Boeing 737-400", "B735": "Boeing 737-500",
    "B736": "Boeing 737-600", "B737": "Boeing 737-700", "B738": "Boeing 737-800", "B739": "Boeing 737-900",
    "B37M": "Boeing 737 MAX 7", "B38M": "Boeing 737 MAX 8", "B39M": "Boeing 737 MAX 9", "B3XM": "Boeing 737 MAX 10",
    "B741": "Boeing 747-100", "B742": "Boeing 747-200", "B744": "Boeing 747-400", "B748": "Boeing 747-8",
    "B752": "Boeing 757-200", "B753": "Boeing 757-300",
    "B762": "Boeing 767-200", "B763": "Boeing 767-300", "B764": "Boeing 767-400",
    "B772": "Boeing 777-200", "B773": "Boeing 777-300", "B77L": "Boeing 777-200LR", "B77W": "Boeing 777-300ER",
    "B788": "Boeing 787-8", "B789": "Boeing 787-9", "B78X": "Boeing 787-10",
    "E170": "Embraer E170", "E75L": "Embraer E175", "E75S": "Embraer E175", "E190": "Embraer E190", "E195": "Embraer E195",
    "E290": "Embraer E190-E2", "E295": "Embraer E195-E2", "E145": "Embraer ERJ-145", "E135": "Embraer ERJ-135",
    "BCS1": "Airbus A220-100", "BCS3": "Airbus A220-300",
    "CRJ2": "Bombardier CRJ-200", "CRJ7": "Bombardier CRJ-700", "CRJ9": "Bombardier CRJ-900", "CRJX": "Bombardier CRJ-1000",
    "DH8D": "De Havilland Dash 8-400", "DH8C": "De Havilland Dash 8-300", "AT72": "ATR 72-500", "AT76": "ATR 72-600",
    "MD11": "McDonnell Douglas MD-11", "MD82": "McDonnell Douglas MD-82", "MD83": "McDonnell Douglas MD-83",
    "MD88": "McDonnell Douglas MD-88", "MD90": "McDonnell Douglas MD-90",
    "C402": "Cessna 402", "C208": "Cessna 208 Caravan", "C172": "Cessna 172",
    "PC12": "Pilatus PC-12", "BE20": "Beechcraft King Air 200", "BE9L": "Beechcraft King Air 90", "B350": "Beechcraft King Air 350",
    "C25A": "Cessna Citation CJ2", "C25B": "Cessna Citation CJ3", "C56X": "Cessna Citation XLS", "C680": "Cessna Citation Sovereign",
    "C68A": "Cessna Citation Latitude", "C700": "Cessna Citation Longitude", "C750": "Cessna Citation X",
    "CL30": "Bombardier Challenger 300", "CL35": "Bombardier Challenger 350", "CL60": "Bombardier Challenger 600",
    "GLF4": "Gulfstream G450", "GLF5": "Gulfstream G550", "GLF6": "Gulfstream G650", "GL5T": "Bombardier Global 5000",
    "GL7T": "Bombardier Global 7500", "GLEX": "Bombardier Global Express",
    "E55P": "Embraer Phenom 300", "E50P": "Embraer Phenom 100", "LJ45": "Learjet 45", "LJ60": "Learjet 60",
    "HDJT": "Honda HondaJet", "PRM1": "Beechcraft Premier I", "FA7X": "Dassault Falcon 7X", "F2TH": "Dassault Falcon 2000",
    "FA50": "Dassault Falcon 50",
    "SR22": "Cirrus SR22", "SR20": "Cirrus SR20", "S22T": "Cirrus SR22T",
    "PA28": "Piper PA-28 Cherokee", "P28A": "Piper PA-28 Archer", "P28R": "Piper PA-28 Arrow", "P28T": "Piper PA-28 Turbo Arrow",
    "PA32": "Piper PA-32 Saratoga", "PA34": "Piper PA-34 Seneca", "PA44": "Piper PA-44 Seminole", "PA46": "Piper PA-46 Malibu",
    "P46T": "Piper PA-46 Meridian", "PA31": "Piper PA-31 Navajo",
    "C150": "Cessna 150", "C152": "Cessna 152", "C177": "Cessna 177 Cardinal", "C182": "Cessna 182 Skylane",
    "C206": "Cessna 206 Stationair", "C210": "Cessna 210 Centurion", "C310": "Cessna 310", "C340": "Cessna 340",
    "C414": "Cessna 414 Chancellor", "C421": "Cessna 421 Golden Eagle",
    "BE36": "Beechcraft Bonanza 36", "BE33": "Beechcraft Bonanza 33", "BE35": "Beechcraft Bonanza 35",
    "BE58": "Beechcraft Baron 58", "BE55": "Beechcraft Baron 55", "BE76": "Beechcraft Duchess",
    "M20P": "Mooney M20", "M20T": "Mooney M20 Turbo", "DA40": "Diamond DA40", "DA42": "Diamond DA42", "DA62": "Diamond DA62",
    "TBM7": "Daher TBM 700", "TBM8": "Daher TBM 850", "TBM9": "Daher TBM 900", "PC24": "Pilatus PC-24", "EPIC": "Epic E1000",
    "COL4": "Cessna 400 Corvalis", "AC11": "Commander 114", "RV10": "Van's RV-10", "RV7": "Van's RV-7", "GA8": "GippsAero GA8 Airvan",
    "R44": "Robinson R44", "R66": "Robinson R66", "EC35": "Airbus Helicopters H135", "EC45": "Airbus Helicopters H145",
    "A109": "Leonardo AW109", "S76": "Sikorsky S-76", "B06": "Bell 206", "B407": "Bell 407", "AS50": "Airbus Helicopters H125",
    "H60": "Sikorsky UH-60 Black Hawk", "GLID": "Glider", "BALL": "Balloon", "UAV": "Drone",
}


def type_long_name(icao: str | None) -> str:
    """'B737' -> 'Boeing 737-700'. Unknown code -> the code itself; empty -> ''."""
    if not icao:
        return ""
    code = icao.upper()
    return LONG_TYPES.get(code) or TYPES.get(code) or code


HEAVIES = {"A332", "A333", "A339", "A342", "A343", "A346", "A359", "A35K", "A388",
           "B744", "B748", "B762", "B763", "B764", "B772", "B773", "B77L", "B77W",
           "B788", "B789", "B78X", "MD11", "A306", "A310"}


def type_name(icao: str | None) -> str:
    if not icao:
        return "UNKNOWN"
    return TYPES.get(icao.upper(), icao.upper())
