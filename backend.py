from flask import Flask, request, jsonify
import math
import requests
import json
import os
from datetime import datetime, timedelta
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

TWILION_ACC_SID       = "twilio sid"
TWILION_AUTH_TOKEN    = " twilio token"
TWILION_PHONE_NUMBER  = +13502503782
EMERGENCY_CALL_TO     = +918220387221

DATA_FILE = "accident_status.json"
logs_list = []
MAX_LOGS  = 100

# =====================================================
# SYSTEM STATE — single source of truth
# =====================================================
state = {
    "accident_detected"   : False,
    "g_force"             : 0.0,
    "lat"                 : None,
    "lon"                 : None,
    "gps_valid"           : False,
    "nearest_hospital"    : "None",
    "nearest_hospital_lat": None,
    "nearest_hospital_lon": None,
    "distance_km"         : 0.0,
    "all_hospitals"       : [],
    "timestamp"           : None,
    "call_made"           : False,
    "hardware_id"         : None,
    "last_ping"           : None,
    "connected"           : False
}

# =====================================================
# UTILITIES
# =====================================================
def log_output(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}"
    logs_list.append(entry)
    if len(logs_list) > MAX_LOGS:
        logs_list.pop(0)
    print(entry)

def save_state():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log_output(f"[WARN] Could not save state: {e}")

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# =====================================================
# HOSPITAL SEARCH via OpenStreetMap
# =====================================================
def osm_find_hospitals(lat, lon, radius_meters=5000):
    log_output(f"Searching hospitals within {radius_meters}m of ({lat:.4f}, {lon:.4f})")
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="hospital"](around:{radius_meters},{lat},{lon});
      way["amenity"="hospital"](around:{radius_meters},{lat},{lon});
      node["amenity"="clinic"](around:{radius_meters},{lat},{lon});
      node["amenity"="doctors"](around:{radius_meters},{lat},{lon});
    );
    out center;
    """
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": "GTrace-Emergency/1.0"},
            timeout=20
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])

        hospitals = []
        for el in elements:
            h_lat = el.get("lat") or el.get("center", {}).get("lat")
            h_lon = el.get("lon") or el.get("center", {}).get("lon")
            name  = el.get("tags", {}).get("name", "")
            if h_lat and h_lon and name:
                dist = haversine(lat, lon, float(h_lat), float(h_lon))
                hospitals.append({
                    "name": name,
                    "lat" : float(h_lat),
                    "lon" : float(h_lon),
                    "dist": dist
                })

        if not hospitals:
            if radius_meters < 15000:
                log_output(f"No hospitals found — expanding to {radius_meters + 5000}m")
                return osm_find_hospitals(lat, lon, radius_meters + 5000)
            log_output("No hospitals found within 15km")
            return None

        hospitals.sort(key=lambda h: h["dist"])
        nearest   = hospitals[0]
        all_names = [f"{h['name']} ({round(h['dist'], 1)} km)" for h in hospitals[:10]]

        log_output(f"Found {len(hospitals)} hospitals. Nearest: {nearest['name']} ({round(nearest['dist'], 2)} km)")
        return nearest["name"], round(nearest["dist"], 2), nearest["lat"], nearest["lon"], all_names

    except requests.exceptions.Timeout:
        log_output("OSM search timed out")
        return None
    except Exception as e:
        log_output(f"OSM error: {e}")
        return None

# =====================================================
# TWILIO EMERGENCY CALL
# =====================================================
def make_emergency_call(lat, lon, g_force, hospital_name, distance_km):
    if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_FROM:
        log_output(f"[MOCK CALL] No Twilio creds — would call {CALL_TO} for {hospital_name}")
        return True
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        twiml = f"""
        <Response>
            <Say voice="alice" loop="2">
                Emergency Alert from G Trace System.
                A vehicle accident has been detected.
                Impact severity: {g_force} G force.
                Accident location: latitude {lat}, longitude {lon}.
                Nearest hospital: {hospital_name},
                approximately {distance_km} kilometers away.
                Google Maps link: https://maps.google.com/?q={lat},{lon}
                Please dispatch an ambulance immediately.
            </Say>
        </Response>
        """
        call = client.calls.create(twiml=twiml, to=CALL_TO, from_=TWILIO_FROM)
        log_output(f"Emergency call placed — SID: {call.sid}")
        return True
    except Exception as e:
        log_output(f"Twilio error: {e}")
        return False

# =====================================================
# CORE ACCIDENT HANDLER
# =====================================================
def handle_accident(g_force, p_lat, p_lon, gps_valid, is_test=False):
    state["accident_detected"] = True
    state["timestamp"]         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["call_made"]         = False

    log_output(f"{'[TEST] ' if is_test else ''}ACCIDENT CONFIRMED — G={g_force:.2f} at ({p_lat:.5f}, {p_lon:.5f})")
    log_output("Querying OpenStreetMap for nearest hospital...")

    result = osm_find_hospitals(p_lat, p_lon)

    if result:
        name, dist, h_lat, h_lon, all_names = result
        state["nearest_hospital"]     = name
        state["nearest_hospital_lat"] = h_lat
        state["nearest_hospital_lon"] = h_lon
        state["distance_km"]          = dist
        state["all_hospitals"]        = all_names
    else:
        state["nearest_hospital"]     = "Call 108 — OSM Unavailable"
        state["nearest_hospital_lat"] = None
        state["nearest_hospital_lon"] = None
        state["distance_km"]          = 0.0
        state["all_hospitals"]        = []
        log_output("OSM unavailable — using fallback")

    log_output(f"Placing emergency call to {CALL_TO}...")
    state["call_made"] = make_emergency_call(
        p_lat, p_lon, g_force,
        state["nearest_hospital"],
        state["distance_km"]
    )
    save_state()
    log_output(f"Response complete. call_made={state['call_made']}")

# =====================================================
# ROUTES
# =====================================================

@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "message"  : "G-Trace Backend Active",
        "endpoints": {
            "POST /data"          : "Receive sensor data from ESP32 {g_force, lat, lon, gps_valid}",
            "GET  /status"        : "Full system state",
            "POST /reset"         : "Reset accident state",
            "POST /test-accident" : "Trigger mock accident for testing",
            "GET  /logs"          : "Recent activity logs",
            "GET  /health"        : "Health check",
            "GET  /hardware"      : "Hardware connection status"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status"            : "ok",
        "accident_active"   : state["accident_detected"],
        "call_made"         : state["call_made"],
        "hardware_connected": state["connected"]
    }), 200


# ── Main endpoint: ESP32 posts here on every loop ──
@app.route("/data", methods=["POST"])
def receive_data():
    try:
        data = request.get_json(force=True)
        if not data or "g_force" not in data:
            return jsonify({"error": "'g_force' field is required"}), 400

        g_force   = float(data["g_force"])
        p_lat     = float(data.get("lat",      11.0830))
        p_lon     = float(data.get("lon",      77.0210))
        gps_valid = bool(data.get("gps_valid", False))

        # Always update live telemetry
        state["g_force"]     = round(g_force, 3)
        state["lat"]         = p_lat
        state["lon"]         = p_lon
        state["gps_valid"]   = gps_valid
        state["hardware_id"] = data.get("hardware_id", "ESP32")
        state["last_ping"]   = datetime.now().isoformat()
        state["connected"]   = True

        log_output(f"Hardware ping — G={g_force:.2f} | GPS={'valid' if gps_valid else 'no-fix'} ({p_lat:.5f}, {p_lon:.5f})")

        accident_override = bool(data.get("accident", False))

        # ACCIDENT TRIGGER: high G-force OR hardware flagged it directly
        if g_force > 10.0 or accident_override:
            # Guard: don't re-trigger if already in accident state
            if not state["accident_detected"]:
                handle_accident(g_force, p_lat, p_lon, gps_valid, is_test=accident_override)

            loc_msg = (
                f"GPS locked: {p_lat:.5f}, {p_lon:.5f}"
                if gps_valid and not (p_lat == 0.0 and p_lon == 0.0)
                else "GPS not fixed — estimated location used"
            )
            return jsonify({
                "accident"     : True,
                "hospital"     : state["nearest_hospital"],
                "distance_km"  : state["distance_km"],
                "hospital_lat" : state["nearest_hospital_lat"],
                "hospital_lon" : state["nearest_hospital_lon"],
                "all_hospitals": state["all_hospitals"],
                "call_made"    : state["call_made"],
                "location"     : loc_msg,
                "timestamp"    : state["timestamp"]
            }), 200

        # Normal driving
        save_state()
        return jsonify({"accident": False, "g_force": g_force, "status": "monitoring"}), 200

    except Exception as e:
        log_output(f"Error in /data: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/status", methods=["GET"])
def check_status():
    if state["last_ping"]:
        try:
            last = datetime.fromisoformat(state["last_ping"])
            state["connected"] = (datetime.now() - last) < timedelta(minutes=5)
        except Exception:
            pass
    return jsonify(state), 200


@app.route("/reset", methods=["POST"])
def reset_system():
    state.update({
        "accident_detected"   : False,
        "g_force"             : 0.0,
        "nearest_hospital"    : "None",
        "nearest_hospital_lat": None,
        "nearest_hospital_lon": None,
        "distance_km"         : 0.0,
        "all_hospitals"       : [],
        "timestamp"           : None,
        "call_made"           : False
    })
    save_state()
    log_output("System reset.")
    return jsonify({"message": "System reset successful"}), 200


@app.route("/test-accident", methods=["POST"])
def test_accident():
    try:
        data     = request.get_json(force=True) or {}
        test_lat = float(data.get("lat", 11.0830))
        test_lon = float(data.get("lon", 77.0210))

        state["g_force"]     = 12.5
        state["lat"]         = test_lat
        state["lon"]         = test_lon
        state["gps_valid"]   = True
        state["hardware_id"] = "TEST_DEVICE"
        state["last_ping"]   = datetime.now().isoformat()
        state["connected"]   = True
        state["accident_detected"] = False   # reset so handle_accident runs fresh

        handle_accident(12.5, test_lat, test_lon, True, is_test=True)

        return jsonify({
            "message"  : "Test accident triggered",
            "hospital" : state["nearest_hospital"],
            "distance" : state["distance_km"],
            "call_made": state["call_made"]
        }), 200
    except Exception as e:
        log_output(f"Test accident error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/logs", methods=["GET"])
def get_logs():
    return jsonify({"logs": logs_list, "count": len(logs_list)}), 200


@app.route("/hardware", methods=["GET"])
def hardware_status():
    if not state["last_ping"]:
        return jsonify({"connected": False, "message": "No ping received yet"}), 200
    try:
        last    = datetime.fromisoformat(state["last_ping"])
        is_conn = (datetime.now() - last) < timedelta(minutes=5)
        return jsonify({
            "connected"  : is_conn,
            "hardware_id": state["hardware_id"],
            "last_ping"  : state["last_ping"],
            "uptime_min" : round((datetime.now() - last).total_seconds() / 60, 1)
        }), 200
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 200


# =====================================================
# STARTUP
# =====================================================
if __name__ == "__main__":
    print("=" * 55)
    print("  G-Trace Emergency Backend")
    print(f"  Twilio : {'Configured' if TWILIO_SID else 'NOT SET — running in mock mode'}")
    print(f"  Call To: {CALL_TO}")
    print(f"  Data   : {os.path.abspath(DATA_FILE)}")
    print("  URL    : http://0.0.0.0:5000")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)
