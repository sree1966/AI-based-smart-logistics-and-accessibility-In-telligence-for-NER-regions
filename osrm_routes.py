"""Real-time road routes between two districts.

Road shape, distance and OSRM travel time come from OSRM (OpenStreetMap roads).
Place names along each road come from OpenStreetMap via Nominatim, sampled
every PLACE_SAMPLE_KM. Rain and flood come from Open-Meteo (live.py), sampled
every SAMPLE_KM along the road.
"""
import math
import time
import requests
import numpy as np
import live

OSRM = "https://router.project-osrm.org/route/v1/driving"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {"User-Agent": "riskroute-student-project/1.0 (academic use)"}
TIMEOUT = 10             # seconds per request
ENDPOINT_KM = 15          # a road must start and end within this distance of the chosen districts
DETOUR_LIMIT = 1.5       # a district is a waypoint candidate if the detour is at most 50 % longer
MAX_STOP_SETS = 5        # direct road plus up to 4 single-district detours
MAX_ROUTES = 3           # show at most three distinct roads
SAMPLE_KM = 1.0          # weather is sampled every km along each road
PLACE_SAMPLE_KM = 40     # a place name is looked up every 40 km along each road
NOMINATIM_DELAY = 1.1    # Nominatim allows about one request per second
STOP_RADIUS_KM = 5       # a catalog district counts as passed if the road comes this close
ASSUMED_SPEED_KMH = 40   # assumption: average speed used for the planning time
HIGH = live.HIGH         # road points above this risk count as high-risk

_place_cache = {}        # successful lookups only: (lat, lon) rounded -> name


def hav(a, b):
    """Great-circle distance in km between two (lon, lat) points."""
    R = 6371.0
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dla, dlo = la2 - la1, math.radians(b[0] - a[0])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def xy(name):
    lat, lon = live.PLACES[name]
    return (lon, lat)


def stop_sets(o, d):
    direct = hav(xy(o), xy(d))
    cands = []
    for name in live.PLACES:
        if name in (o, d):
            continue
        detour = (hav(xy(o), xy(name)) + hav(xy(name), xy(d))) / direct
        if detour <= DETOUR_LIMIT:
            cands.append((detour, name))
    cands.sort()
    return [[]] + [[n] for _, n in cands[:MAX_STOP_SETS - 1]]


def osrm(points):
    coords = ";".join(f"{lon},{lat}" for lon, lat in points)
    r = requests.get(f"{OSRM}/{coords}",
                     params={"alternatives": "true", "overview": "full", "geometries": "geojson"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("routes", [])


def resample(geom, step_km):
    """Points about step_km apart along a [lon, lat] line, including both ends."""
    out, acc = [geom[0]], 0.0
    for a, b in zip(geom[:-1], geom[1:]):
        acc += hav(a, b)
        if acc >= step_km:
            out.append(b)
            acc = 0.0
    if tuple(out[-1]) != tuple(geom[-1]):
        out.append(geom[-1])
    return out


def place_name(lon, lat):
    """Town or district name at a point from OpenStreetMap. None if unavailable.
    Failed lookups are not cached, so they can be retried on the next search."""
    key = (round(lat, 2), round(lon, 2))
    if key in _place_cache:
        return _place_cache[key]
    time.sleep(NOMINATIM_DELAY)
    try:
        r = requests.get(NOMINATIM,
                         params={"lat": lat, "lon": lon, "format": "jsonv2",
                                 "zoom": 10, "addressdetails": 1},
                         headers=NOMINATIM_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        addr = r.json().get("address", {})
    except (requests.RequestException, ValueError):
        return None
    name = None
    for field in ("town", "city", "village", "municipality", "county", "state_district"):
        if addr.get(field):
            name = addr[field]
            break
    _place_cache[key] = name
    return name


def road_places(geom, o, d):
    """Place names along the road in travel order, skipping repeats and the endpoints."""
    names = []
    for lon, lat in resample(geom, PLACE_SAMPLE_KM):
        name = place_name(lon, lat)
        if name and name not in names and name not in (o, d):
            names.append(name)
    return names


def catalog_places(samples, o, d):
    """Fallback: catalog districts within STOP_RADIUS_KM of the road, in travel order."""
    found = []
    for name in live.PLACES:
        if name in (o, d):
            continue
        dists = [hav(p, xy(name)) for p in samples]
        i = int(np.argmin(dists))
        if dists[i] <= STOP_RADIUS_KM:
            found.append((i, name))
    return [n for _, n in sorted(found)]


def describe(r, o, d):
    geom = r["geometry"]["coordinates"]
    samples = resample(geom, SAMPLE_KM)
    c = live.components_along(samples)
    risk = np.asarray(c["risk"], dtype=float)
    stops = road_places(geom, o, d) or catalog_places(samples, o, d)
    km = round(r["distance"] / 1000, 1)
    return {
        "path": " → ".join([o] + stops + [d]),
        "stops": stops,
        "km": km,
        "osrm_minutes": round(r["duration"] / 60),
        "assumed_minutes": round(km / ASSUMED_SPEED_KMH * 60),
        "avg_risk": round(float(risk.mean()), 3),
        "rain_risk": round(float(np.mean(c["rain_risk"])), 3),
        "flood_risk": round(float(np.mean(c["flood_risk"])), 3),
        "rain_mm": round(float(np.mean(c["rain_mm"])), 1),
        "km_high_risk": round(float((risk > HIGH).sum()) * SAMPLE_KM, 1),
        "geometry": [[round(lat, 5), round(lon, 5)] for lon, lat in geom],   # Leaflet order
    }


def build(o, d):
    if o not in live.PLACES or d not in live.PLACES:
        raise KeyError("Unknown district.")
    if o == d:
        raise ValueError("Choose two different districts.")
    O, D = xy(o), xy(d)
    candidates = []
    for via in stop_sets(o, d):
        points = [O] + [xy(n) for n in via] + [D]
        try:
            raw = osrm(points)
        except requests.RequestException:
            continue
        valid = [r for r in raw
                 if hav(r["geometry"]["coordinates"][0], O) <= ENDPOINT_KM
                 and hav(r["geometry"]["coordinates"][-1], D) <= ENDPOINT_KM]
        if valid:
            candidates.append(min(valid, key=lambda r: r["duration"]))
    if not candidates:
        raise RuntimeError("OSRM returned no valid road between these districts. Try again shortly.")

    routes, seen_paths, seen_roads = [], set(), set()
    for best in candidates:
        road_key = tuple(map(tuple, best["geometry"]["coordinates"][::25]))
        if road_key in seen_roads:
            continue
        seen_roads.add(road_key)
        route = describe(best, o, d)
        # Silently drop a road that is the same as one already kept, or a
        # "direct" road that passes no named place when a road with places exists.
        if tuple(route["stops"]) in seen_paths:
            continue
        seen_paths.add(tuple(route["stops"]))
        routes.append(route)

    if any(r["stops"] for r in routes):
        routes = [r for r in routes if r["stops"]]

    TIE = 0.05   # assumption: risk differences up to this are treated as no real difference
    best_risk = min(r["avg_risk"] for r in routes)

    def _rank(x):
        if x["avg_risk"] - best_risk <= TIE:
            return (0, x["assumed_minutes"])   # tied on risk: fastest first
        return (1, x["avg_risk"])              # clearly riskier: sorted by risk

    routes.sort(key=_rank)
    routes = routes[:MAX_ROUTES]
    for i, r in enumerate(routes):
        r["id"] = f"route-{i + 1}"
        r["label"] = f"Route {i + 1}"
        r["recommended"] = i == 0
    return {"origin": o, "destination": d,
            "fetched_at": live.ST["fetched_at"],
            "weather": live.status(),
            "assumed_speed_kmh": ASSUMED_SPEED_KMH,
            "routes": routes}
