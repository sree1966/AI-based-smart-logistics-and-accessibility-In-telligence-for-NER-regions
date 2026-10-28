"""Live road-risk layer for the Northeast.

Today's rainfall (Open-Meteo forecast) and river flood (Open-Meteo flood API) are fetched
on a regional grid, not a road map, so no OpenStreetMap file is needed. Each road point
takes the risk of its nearest grid cell. All values are real; the only assumptions are
the thresholds marked below.
"""
import threading, time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

IST = timezone(timedelta(hours=5, minutes=30))

RAIN_CAP_MM = 200          # assumption: 4-day rainfall at or above this = maximum rain risk
FLOOD_FULL = 3.0           # assumption: discharge at 3x its 30-day median = maximum flood risk
HIGH = 0.6                 # risk above this counts as high-risk road
TTL = 1800                 # seconds before weather is fetched again
BATCH = 25                 # grid points per Open-Meteo request

# Grid covering Assam, Meghalaya, Nagaland, Manipur, Tripura, Mizoram and the Barak valley.
GRID_STEP = 0.25
LAT_RANGE = (21.5, 28.0)
LON_RANGE = (89.5, 97.5)
_lats = np.arange(LAT_RANGE[0], LAT_RANGE[1] + 1e-9, GRID_STEP)
_lons = np.arange(LON_RANGE[0], LON_RANGE[1] + 1e-9, GRID_STEP)
GLAT, GLON = (a.ravel() for a in np.meshgrid(np.round(_lats, 2), np.round(_lons, 2), indexing="ij"))
COS = np.cos(np.radians(26.0))   # longitude scale so nearest-point distances are roughly right

# District centres used as stops. Coordinates are approximate town centres.
PLACES = {
    "Guwahati":   (26.1445, 91.7458),
    "Morigaon":   (26.24908, 92.34764),
    "Nagaon":     (26.35, 92.66667),
    "Hojai":      (26.00281, 92.85605),
    "Haflong":    (25.16478, 93.01744),
    "Silchar":    (24.8333, 92.7789),
    "Hailakandi": (24.68394, 92.56097),
    "Sribhumi":   (24.86919, 92.35543),
}

ST = {"ready": False, "error": None, "ts": 0.0, "fetched_at": None, "info": {}}
RISK = None                # risk per grid cell, 0 to 1
RAIN_R = FLOOD_R = RAIN_MM = None   # rain risk, flood risk and 4-day rain (mm) per grid cell
REFRESH_LOCK = threading.Lock()


def _fetch(url, var, extra):
    out = []
    for s in range(0, len(GLAT), BATCH):
        params = {"latitude": ",".join(f"{x:.2f}" for x in GLAT[s:s + BATCH]),
                  "longitude": ",".join(f"{x:.2f}" for x in GLON[s:s + BATCH]),
                  "daily": var, "timezone": "Asia/Kolkata", **extra}
        res = None
        for attempt in range(4):
            try:
                r = requests.get(url, params=params, timeout=60)
            except requests.RequestException:
                time.sleep(5 * (attempt + 1))   # connection dropped: wait and retry
                continue
            if r.status_code == 200:
                data = r.json()
                res = data if isinstance(data, list) else [data]
                break
            if r.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            break
        n = len(GLAT[s:s + BATCH])
        if res is None or len(res) != n:
            out += [None] * n
        else:
            out += [[x["daily"]["time"], x["daily"][var]] for x in res]
        time.sleep(1)
    return out


def _fill(values, ok):
    """Replace missing grid values with the median of the good ones, or 0 if none are good."""
    if not ok:
        return np.where(np.isnan(values), 0.0, values)
    return np.where(np.isnan(values), np.nanmedian(values), values)


def refresh(force=False):
    with REFRESH_LOCK:
        global RISK, RAIN_R, FLOOD_R, RAIN_MM
        if ST["ready"] and not force and time.time() - ST["ts"] < TTL:
            return
        day = datetime.now(IST).date()
        day_s = day.isoformat()
        rain = _fetch("https://api.open-meteo.com/v1/forecast", "precipitation_sum",
                      {"past_days": 3, "forecast_days": 1})
        flood = _fetch("https://flood-api.open-meteo.com/v1/flood", "river_discharge",
                       {"past_days": 30, "forecast_days": 1})

        def rain_total(tv):
            if not tv:
                return np.nan
            t, v = tv
            vals = [x for ti, x in zip(t, v) if x is not None
                    and day - timedelta(days=3) <= datetime.fromisoformat(ti).date() <= day]
            return float(sum(vals)) if vals else np.nan

        def flood_risk(tv):
            if not tv or day_s not in tv[0]:
                return np.nan
            t, v = tv
            i = t.index(day_s)
            hist = [x for x in v[:i] if x is not None]
            if v[i] is None or not hist:
                return np.nan
            base = max(float(np.median(hist)), 0.1)
            return float(np.clip((v[i] / base - 1) / (FLOOD_FULL - 1), 0, 1))

        rm = np.array([rain_total(v) for v in rain], dtype=float)
        fr = np.array([flood_risk(v) for v in flood], dtype=float)
        rain_ok = not np.isnan(rm).all()
        flood_ok = not np.isnan(fr).all()
        if not rain_ok and not flood_ok:
            raise RuntimeError("Open-Meteo returned no usable data. Check your internet connection and try again.")

        miss = {"rain": int(np.isnan(rm).sum()), "flood": int(np.isnan(fr).sum())}
        rr = _fill(np.clip(rm / RAIN_CAP_MM, 0, 1), rain_ok)
        fr = _fill(fr, flood_ok)
        RISK = 0.5 * rr + 0.5 * fr
        RAIN_R, FLOOD_R, RAIN_MM = rr, fr, _fill(rm, rain_ok)

        ST.update(ready=True, error=None, ts=time.time(),
                  fetched_at=datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST"),
                  info={"date": day_s, "grid_points": int(len(GLAT)), "missing": miss,
                        "rain_ok": bool(rain_ok), "flood_ok": bool(flood_ok),
                        "rain_mm_mean": round(float(np.nanmean(rm)), 1) if rain_ok else None,
                        "rain_mm_max": round(float(np.nanmax(rm)), 1) if rain_ok else None})


def start():
    try:
        refresh(force=True)
    except Exception as ex:
        ST["error"] = str(ex)


def wait_ready(timeout=300):
    t0 = time.time()
    while not ST["ready"] and not ST["error"] and time.time() - t0 < timeout:
        time.sleep(1)
    if not ST["ready"]:
        raise RuntimeError(ST["error"] or "Weather data is still loading. Try again in a minute.")


def _nearest(lonlat):
    wait_ready()
    refresh()                                   # refetches only if older than TTL
    arr = np.asarray(lonlat, dtype=float)
    dlat = arr[:, 1, None] - GLAT[None, :]
    dlon = (arr[:, 0, None] - GLON[None, :]) * COS
    return np.argmin(dlat ** 2 + dlon ** 2, axis=1)


def risk_along(lonlat):
    """Risk (0 to 1) for each [lon, lat] point: the risk of its nearest grid cell."""
    return RISK[_nearest(lonlat)]


def components_along(lonlat):
    """Rain risk, flood risk, 4-day rain (mm) and combined risk for each [lon, lat] point."""
    idx = _nearest(lonlat)
    return {"risk": RISK[idx], "rain_risk": RAIN_R[idx], "flood_risk": FLOOD_R[idx], "rain_mm": RAIN_MM[idx]}


def status():
    return {"ready": ST["ready"], "fetched_at": ST["fetched_at"], "error": ST["error"], **ST["info"]}