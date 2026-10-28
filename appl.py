import threading
from flask import Flask, abort, jsonify, render_template
from werkzeug.exceptions import HTTPException
import live
import osrm_routes

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/osrm/places")
def places():
    return jsonify({name: {"lat": lat, "lon": lon}
                    for name, (lat, lon) in live.PLACES.items()})


@app.route("/api/live/status")
def status():
    return jsonify(live.status())


@app.route("/api/live/osrm/<o>/<d>")
def live_osrm(o, d):
    try:
        return jsonify(osrm_routes.build(o, d))
    except KeyError as ex:
        abort(404, description=str(ex.args[0]))
    except ValueError as ex:
        abort(400, description=str(ex))
    except RuntimeError as ex:
        abort(503, description=str(ex))
    except Exception as ex:
        abort(502, description="Road routing or weather is unavailable: " + str(ex))


@app.errorhandler(HTTPException)
def http_error(e):
    return jsonify({"error": e.description}), e.code


if __name__ == "__main__":
    threading.Thread(target=live.start, daemon=True).start()   # fetch weather in the background
    app.run(debug=False, threaded=True)
