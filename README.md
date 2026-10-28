# Assam Road Risk: Live Routing

A web app that finds road routes between districts in Assam and the Northeast, and shows how risky each route is today.

## What it does

- Finds road routes between two districts using OSRM (OpenStreetMap roads), including routes that pass through intermediate districts.
- Shows, for each route: distance, travel time at an assumed speed, estimated diesel use and cost, and the districts it passes.
- Scores each route with today's rainfall (last 4 days) and river flood levels from Open-Meteo, sampled along the road.
- Ranks routes from lowest to highest risk, and lets you compare distance with Google Maps.

## Data sources

- **Road network and distances:** OSRM public routing service, built on OpenStreetMap data.
- **Rainfall and river discharge:** Open-Meteo forecast and flood APIs. Real data, refreshed every 30 minutes.
- **Map tiles:** OpenStreetMap.

## Assumptions (not measured data)

- **Risk thresholds:** rainfall is scored against a 200 mm cap, and flood risk is measured against 3 times the 30-day median discharge. Rain and flood have equal weight.
- **Travel time:** uses an assumed average speed of 40 km/h.
- **Diesel:** uses an assumed truck mileage of 4 km/l and a diesel price of ₹92/l. Both can be changed in the app.
- **District coordinates:** approximate town-centre points.

## Limitations

- Weather is sampled on a grid about 28 km apart, so nearby roads can share the same values.
- Routes come from the public OSRM server, which may be slow or rate-limited.
- Results are a planning aid, not a substitute for local road or weather advisories.

## Requirements

- Python 3.10 or newer
- Internet access (for OSRM, Open-Meteo and map tiles)

## Setup and run

```
pip install -r requirements.txt
python appl.py
```

Then open http://127.0.0.1:5000. The first search takes a minute or two while weather data loads.

On Windows PowerShell, you can use a virtual environment:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python appl.py
```

## Using the app

1. Choose a **From** and **To** district and press **Find routes**.
2. Each route is shown as a numbered card. Route 1 is the lowest-risk option.
3. Click a card or a line on the map to highlight that route.
4. Adjust the assumptions on the left (speed, mileage, diesel price, Google Maps distance). The cards update without a new search.

## Project structure

```
riskroute/
├── appl.py            # Flask server and API
├── live.py            # Weather grid and risk calculation
├── osrm_routes.py     # Road routes, stops, distance and time
├── requirements.txt   # Python packages
├── README.md
└── templates/
    └── index.html     # Map and route cards
```

## API

| Endpoint | Returns |
|---|---|
| `/` | The map page |
| `/api/osrm/places` | District names and coordinates |
| `/api/live/osrm/<from>/<to>` | Routes with distance, time, weather and risk values |
| `/api/live/status` | Weather status and the data date |

## License

Add a license here, for example MIT.
