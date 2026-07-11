"""Locality → coordinates lookup and distance-from-origin filtering.

Sites differ wildly in how (and whether) they support radius search, so the
scraper requests broad result sets and filters here: parse the listing's
location text, resolve it to coordinates, and compute the straight-line
distance from the origin (Cairns by default).

Resolution order for a location string like "Trinity Beach, QLD 4879":
  1. locality name in the table below — but only when it doesn't contradict
     an explicit state in the text (several town names exist in more than
     one state),
  2. QLD postcode ranges (4xxx),
  3. state fallback: other-state capitals are all far outside any sane
     Cairns radius, which is enough to exclude them.

Unknown-but-possibly-QLD locations are kept and flagged rather than dropped
(configurable) — for rare EVs a false inclusion beats a silent miss.
"""

from __future__ import annotations

import math
import re

CAIRNS = (-16.9186, 145.7781)

# Cairns suburbs all sit within ~25 km of the city centre — at a 250 km radius
# the difference is noise, so they share the city's coordinates.
_CAIRNS_SUBURBS = [
    "cairns city", "cairns north", "parramatta park", "manunda", "manoora",
    "westcourt", "bungalow", "portsmith", "woree", "earlville", "mooroobool",
    "kanimbla", "brinsmead", "freshwater", "stratford", "whitfield",
    "edge hill", "aeroglen", "machans beach", "holloways beach",
    "yorkeys knob", "trinity park", "trinity beach", "kewarra beach",
    "clifton beach", "palm cove", "smithfield", "caravonica", "redlynch",
    "bayview heights", "mount sheridan", "white rock", "bentley park",
    "edmonton", "gordonvale", "packers camp", "barron", "kamerunga",
]

# name -> (lat, lng, state)
LOCALITIES: dict[str, tuple[float, float, str]] = {
    "cairns": (*CAIRNS, "QLD"),
    # Far North Queensland
    "port douglas": (-16.4834, 145.4652, "QLD"),
    "mossman": (-16.4620, 145.3720, "QLD"),
    "kuranda": (-16.8190, 145.6380, "QLD"),
    "mareeba": (-17.0000, 145.4230, "QLD"),
    "atherton": (-17.2670, 145.4750, "QLD"),
    "tolga": (-17.2240, 145.4790, "QLD"),
    "malanda": (-17.3530, 145.5940, "QLD"),
    "yungaburra": (-17.2720, 145.5830, "QLD"),
    "millaa millaa": (-17.5110, 145.6130, "QLD"),
    "ravenshoe": (-17.6060, 145.4830, "QLD"),
    "babinda": (-17.3440, 145.9220, "QLD"),
    "innisfail": (-17.5300, 146.0300, "QLD"),
    "south johnstone": (-17.6060, 146.0000, "QLD"),
    "mission beach": (-17.8680, 146.1030, "QLD"),
    "tully": (-17.9330, 145.9230, "QLD"),
    "cardwell": (-18.2670, 146.0300, "QLD"),
    "ingham": (-18.6500, 146.1600, "QLD"),
    "cooktown": (-15.4680, 145.2500, "QLD"),
    "weipa": (-12.6300, 141.8790, "QLD"),
    "thursday island": (-10.5820, 142.2190, "QLD"),
    # North / Central Queensland
    "townsville": (-19.2580, 146.8180, "QLD"),
    "thuringowa": (-19.3200, 146.7300, "QLD"),
    "kirwan": (-19.3060, 146.7290, "QLD"),
    "aitkenvale": (-19.2980, 146.7730, "QLD"),
    "garbutt": (-19.2560, 146.7690, "QLD"),
    "ayr": (-19.5730, 147.4060, "QLD"),
    "home hill": (-19.6620, 147.4160, "QLD"),
    "charters towers": (-20.0770, 146.2610, "QLD"),
    "bowen": (-20.0130, 148.2470, "QLD"),
    "proserpine": (-20.4010, 148.5810, "QLD"),
    "airlie beach": (-20.2680, 148.7180, "QLD"),
    "cannonvale": (-20.2770, 148.6980, "QLD"),
    "mackay": (-21.1410, 149.1860, "QLD"),
    "moranbah": (-22.0020, 148.0470, "QLD"),
    "emerald": (-23.5270, 148.1610, "QLD"),
    "rockhampton": (-23.3750, 150.5100, "QLD"),
    "yeppoon": (-23.1270, 150.7440, "QLD"),
    "gladstone": (-23.8430, 151.2560, "QLD"),
    "biloela": (-24.4000, 150.5130, "QLD"),
    "bundaberg": (-24.8660, 152.3510, "QLD"),
    "hervey bay": (-25.2880, 152.8410, "QLD"),
    "maryborough": (-25.5380, 152.7020, "QLD"),
    "gympie": (-26.1900, 152.6650, "QLD"),
    "kingaroy": (-26.5410, 151.8390, "QLD"),
    # South East Queensland
    "sunshine coast": (-26.6500, 153.0670, "QLD"),
    "maroochydore": (-26.6560, 153.0910, "QLD"),
    "caloundra": (-26.8030, 153.1330, "QLD"),
    "noosa heads": (-26.3980, 153.0880, "QLD"),
    "noosaville": (-26.3990, 153.0620, "QLD"),
    "nambour": (-26.6260, 152.9590, "QLD"),
    "caboolture": (-27.0850, 152.9510, "QLD"),
    "brisbane": (-27.4700, 153.0250, "QLD"),
    "ipswich": (-27.6150, 152.7600, "QLD"),
    "logan": (-27.6390, 153.1090, "QLD"),
    "logan central": (-27.6390, 153.1090, "QLD"),
    "springwood": (-27.6130, 153.1350, "QLD"),
    "beenleigh": (-27.7110, 153.2030, "QLD"),
    "gold coast": (-28.0170, 153.4000, "QLD"),
    "southport": (-27.9670, 153.4140, "QLD"),
    "nerang": (-27.9890, 153.3360, "QLD"),
    "robina": (-28.0760, 153.3840, "QLD"),
    "toowoomba": (-27.5610, 151.9540, "QLD"),
    "warwick": (-28.2150, 152.0350, "QLD"),
    "roma": (-26.5730, 148.7870, "QLD"),
    "mount isa": (-20.7260, 139.4930, "QLD"),
    "longreach": (-23.4420, 144.2500, "QLD"),
    # Other-state capitals & majors — far enough that precision is irrelevant.
    "sydney": (-33.8690, 151.2090, "NSW"),
    "newcastle": (-32.9270, 151.7800, "NSW"),
    "wollongong": (-34.4240, 150.8930, "NSW"),
    "melbourne": (-37.8140, 144.9630, "VIC"),
    "geelong": (-38.1470, 144.3600, "VIC"),
    "adelaide": (-34.9290, 138.6010, "SA"),
    "perth": (-31.9520, 115.8610, "WA"),
    "hobart": (-42.8820, 147.3270, "TAS"),
    "launceston": (-41.4390, 147.1350, "TAS"),
    "darwin": (-12.4630, 130.8420, "NT"),
    "alice springs": (-23.6980, 133.8810, "NT"),
    "canberra": (-35.2810, 149.1290, "ACT"),
}
for _s in _CAIRNS_SUBURBS:
    LOCALITIES[_s] = (*CAIRNS, "QLD")

# QLD postcode prefixes → representative locality. Checked longest-first.
_POSTCODE_MAP: list[tuple[str, str]] = [
    ("487", "cairns"),        # 4870-4879 Cairns & near suburbs
    ("4880", "mareeba"),
    ("4881", "kuranda"),
    ("4882", "tolga"),
    ("4883", "atherton"),
    ("4884", "yungaburra"),
    ("4885", "malanda"),
    ("4886", "millaa millaa"),
    ("4887", "atherton"),     # Herberton area
    ("4888", "ravenshoe"),
    ("4895", "cooktown"),
    ("4861", "babinda"),
    ("4860", "innisfail"),
    ("4859", "south johnstone"),
    ("4852", "mission beach"),
    ("4854", "tully"),
    ("4849", "cardwell"),
    ("4850", "ingham"),
    ("4874", "weipa"),
    ("4875", "thursday island"),
    ("481", "townsville"),    # 4810-4819
    ("4807", "ayr"),
    ("4806", "home hill"),
    ("4820", "charters towers"),
    ("4805", "bowen"),
    ("4800", "proserpine"),
    ("4802", "airlie beach"),
    ("474", "mackay"),        # 4740-4749
    ("4744", "moranbah"),
    ("4720", "emerald"),
    ("470", "rockhampton"),   # 4700-4709
    ("4703", "yeppoon"),
    ("4680", "gladstone"),
    ("4715", "biloela"),
    ("4670", "bundaberg"),
    ("4655", "hervey bay"),
    ("4650", "maryborough"),
    ("4570", "gympie"),
    ("4610", "kingaroy"),
    ("455", "sunshine coast"),
    ("456", "sunshine coast"),
    ("4510", "caboolture"),
    ("435", "toowoomba"),
    ("4370", "warwick"),
    ("4455", "roma"),
    ("4825", "mount isa"),
    ("4730", "longreach"),
    ("40", "brisbane"),       # 4000-4099
    ("41", "brisbane"),       # 4100-4199 (Brisbane south / Logan edges)
    ("430", "ipswich"),
    ("4114", "logan"),
    ("421", "gold coast"),    # 4210-4219
    ("422", "gold coast"),
    ("423", "gold coast"),
]

_STATE_FALLBACK = {
    "NSW": "sydney",
    "VIC": "melbourne",
    "SA": "adelaide",
    "WA": "perth",
    "TAS": "hobart",
    "NT": "darwin",
    "ACT": "canberra",
}

_STATE_NAMES = {
    "queensland": "QLD", "new south wales": "NSW", "victoria": "VIC",
    "south australia": "SA", "western australia": "WA", "tasmania": "TAS",
    "northern territory": "NT", "australian capital territory": "ACT",
}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def extract_state(location_text: str | None) -> str | None:
    """Pull an Australian state abbreviation out of free location text.

    Text naming several different states (nav bars, state-filter lists) is
    ambiguous — return None so the listing is flagged unknown instead of
    being confidently mislocated.
    """
    if not location_text:
        return None
    text = location_text.lower()
    found = {m.group(1).upper()
             for m in re.finditer(r"\b(qld|nsw|vic|sa|wa|tas|nt|act)\b", text)}
    for name, abbr in _STATE_NAMES.items():
        if name in text:
            found.add(abbr)
    if len(found) == 1:
        return next(iter(found))
    return None


def _postcode_locality(location_text: str) -> str | None:
    m = re.search(r"\b(4\d{3})\b", location_text)
    if not m:
        return None
    pc = m.group(1)
    for prefix, locality in sorted(_POSTCODE_MAP, key=lambda t: -len(t[0])):
        if pc.startswith(prefix):
            return locality
    return None


def resolve_coords(location_text: str | None) -> tuple[float, float] | None:
    """Best-effort coordinates for a listing's location string."""
    if not location_text:
        return None
    text = re.sub(r"[^a-z0-9\s]", " ", location_text.lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    state = extract_state(location_text)
    # Longest names first so "port douglas" wins over a bare "douglas"-style
    # substring; skip localities that contradict an explicit state.
    for name in sorted(LOCALITIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text):
            lat, lng, loc_state = LOCALITIES[name]
            if state is not None and state != loc_state:
                continue
            return (lat, lng)
    # 4xxx postcodes are Queensland; only trust them when the text doesn't
    # claim another state (avoids street/unit numbers that look like one).
    if state in (None, "QLD"):
        pc_loc = _postcode_locality(text)
        if pc_loc:
            lat, lng, _ = LOCALITIES[pc_loc]
            return (lat, lng)
    if state and state in _STATE_FALLBACK:
        lat, lng, _ = LOCALITIES[_STATE_FALLBACK[state]]
        return (lat, lng)
    return None


def distance_km(location_text: str | None,
                origin: tuple[float, float] = CAIRNS) -> float | None:
    coords = resolve_coords(location_text)
    if coords is None:
        return None
    return round(haversine_km(origin, coords), 1)
