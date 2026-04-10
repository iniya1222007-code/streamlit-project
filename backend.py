from flask import Flask, request, jsonify
import math
import requests
import json
import os
from datetime import datetime
from twilio.rest import Client

app = Flask(__name__)

TWILIO_SID   = "twilio SID"
TWILIO_TOKEN = "twilio token"
TWILIO_FROM  = "+17543184157"
CALL_TO      = "+7010467865"

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
    "connected"           : False,
    "hardware_id"         : None,
    "logs"                : []
}

DATA_FILE = "accident_status.json"


def make_emergency_call(lat, lon, g_force, hospital_name, distance_km):
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)

        twiml_message = f"""
        <Response>
            <Say voice="alice" loop="2">
                Emergency Alert from G Trace System.
                Vehicle accident detected.
                Impact severity {g_force} G force.
                Accident location coordinates,
                {lat} latitude, {lon} longitude.
                Nearest hospital is {hospital_name},
                approximately {distance_km} kilometers away.
                Google Maps link,
                https://maps.google.com/?q={lat},{lon}
                Please dispatch ambulance immediately.
            </Say>
        </Response>
        """

        call = client.calls.create(
            twiml  = twiml_message,
            to     = CALL_TO,
            from_  = TWILIO_FROM
        )

        print(f"✅ Emergency call made! SID: {call.sid}")
        return True

    except Exception as e:
        print(f"❌ Twilio call error: {e}")
        return False


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def osm_find_hospitals(lat, lon, radius_meters=5000):
    overpass_query = f"""
    [out:json][timeout:15];
    (
      node["amenity"="hospital"](around:{radius_meters},{lat},{lon});
      way["amenity"="hospital"](around:{radius_meters},{lat},{lon});
      node["amenity"="clinic"](around:{radius_meters},{lat},{lon});
      node["amenity"="doctors"](around:{radius_meters},{lat},{lon});
    );
    out center;
    """
    try:
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": overpass_query},
            headers={"User-Agent": "GTrace-Emergency/1.0"},
            timeout=12
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])

        hospitals = []
        for el in elements:
            h_lat = el.get("lat") or el.get("center", {}).get("lat")
            h_lon = el.get("lon") or el.get("center", {}).get("lon")
            name  = el.get("tags", {}).get("name", "Unnamed Hospital")

            if h_lat and h_lon and name != "Unnamed Hospital":
                dist = haversine(lat, lon, float(h_lat), float(h_lon))
                hospitals.append({
                    "name": name,
                    "lat" : float(h_lat),
                    "lon" : float(h_lon),
                    "dist": dist
                })

        if not hospitals:
            if radius_meters < 15000:
                print(f"⚠ No hospitals within {radius_meters}m → expanding...")
                return osm_find_hospitals(lat, lon, radius_meters + 5000)
            print("❌ No hospitals found within 15km")
            return None

        hospitals.sort(key=lambda h: h["dist"])
        nearest   = hospitals[0]
        all_names = [f"{h['name']} ({round(h['dist'], 1)} km)" for h in hospitals]

        print(f"✅ OSM: {len(hospitals)} hospitals found")
        print(f"   Nearest → {nearest['name']} ({round(nearest['dist'], 2)} km)")

        return nearest["name"], round(nearest["dist"], 2), nearest["lat"], nearest["lon"], all_names

    except requests.exceptions.Timeout:
        print("❌ Overpass API timed out")
        return None
    except Exception as e:
        print(f"❌ OSM error: {e}")
        return None


def save_state():
    with open(DATA_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                loaded = json.load(f)
                state.update(loaded)
        except Exception as e:
            print(f"⚠ Could not load saved state: {e}")


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{timestamp} | {message}"
    print(entry)
    state["logs"].append(entry)
    if len(state["logs"]) > 100:
        state["logs"] = state["logs"][-100:]
    save_state()


@app.route("/data", methods=["POST"])
def receive_data():
    try:
        data = request.get_json(force=True)
        if not data or "g_force" not in data:
            return jsonify({"error": "'g_force' is required"}), 400

        g_force   = float(data["g_force"])
        p_lat     = float(data.get("lat", 11.0830))
        p_lon     = float(data.get("lon", 77.0219))
        gps_valid = bool(data.get("gps_valid", False))

        state["g_force"]       = round(g_force, 3)
        state["lat"]           = p_lat
        state["lon"]           = p_lon
        state["gps_valid"]     = gps_valid
        state["connected"]     = True
        state["hardware_id"]   = data.get("hardware_id", "ESP32")

        log(f"Received data from {state['hardware_id']}: G={g_force:.2f}, GPS={'valid' if gps_valid else 'invalid'}, lat={p_lat:.5f}, lon={p_lon:.5f}")

        accident_flag = bool(data.get("accident", False))
        accident_detected = g_force > 4.0 or accident_flag

        if accident_detected:
            state["accident_detected"] = True
            state["timestamp"]         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            state["call_made"]         = False

            log(f"🚨 ACCIDENT CONFIRMED at ({p_lat}, {p_lon})")
            log("🔍 Querying OSM for nearest hospital...")

            result = osm_find_hospitals(p_lat, p_lon)

            if result:
                name, dist, h_lat, h_lon, all_names = result
                state["nearest_hospital"]       = name
                state["nearest_hospital_lat"]   = h_lat
                state["nearest_hospital_lon"]   = h_lon
                state["distance_km"]            = dist
                state["all_hospitals"]          = all_names

                log(f"📞 Calling emergency contact...")
                call_success = make_emergency_call(
                    p_lat, p_lon,
                    round(g_force, 2),
                    name, dist
                )
                state["call_made"] = call_success

            else:
                state["nearest_hospital"]     = "OSM Unavailable — Call 108"
                state["nearest_hospital_lat"] = None
                state["nearest_hospital_lon"] = None
                state["distance_km"]          = 0.0
                state["all_hospitals"]        = []

                log(f"📞 Calling emergency contact (no hospital found)...")
                call_success = make_emergency_call(
                    p_lat, p_lon,
                    round(g_force, 2),
                    "unknown, please check maps", 0
                )
                state["call_made"] = call_success

            save_state()

            return jsonify({
                "accident"     : True,
                "hospital"     : state["nearest_hospital"],
                "distance_km"  : state["distance_km"],
                "hospital_lat" : state["nearest_hospital_lat"],
                "hospital_lon" : state["nearest_hospital_lon"],
                "all_hospitals": state["all_hospitals"],
                "location"     : [p_lat, p_lon],
                "call_made"    : state["call_made"]
            }), 200

        save_state()
        return jsonify({"accident": False, "g_force": g_force}), 200

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/status", methods=["GET"])
def check_status():
    return jsonify(state), 200

@app.route("/logs", methods=["GET"])
def get_logs():
    return jsonify({"logs": state.get("logs", [])}), 200

@app.route("/test-accident", methods=["POST"])
def test_accident():
    data = request.get_json(silent=True) or {}
    lat = float(data.get("lat", 11.0830))
    lon = float(data.get("lon", 77.0210))
    gps_valid = True
    g_force = 12.0

    log("🧪 Test accident triggered")
    state["connected"] = True
    state["hardware_id"] = data.get("hardware_id", "ESP32-Test")

    result = osm_find_hospitals(lat, lon)
    if result:
        name, dist, h_lat, h_lon, all_names = result
        state["nearest_hospital"]       = name
        state["nearest_hospital_lat"]   = h_lat
        state["nearest_hospital_lon"]   = h_lon
        state["distance_km"]            = dist
        state["all_hospitals"]          = all_names
        log(f"📞 Calling emergency contact for test accident")
        call_success = make_emergency_call(lat, lon, g_force, name, dist)
        state["call_made"] = call_success
    else:
        state["nearest_hospital"]     = "OSM Unavailable — Call 108"
        state["nearest_hospital_lat"] = None
        state["nearest_hospital_lon"] = None
        state["distance_km"]          = 0.0
        state["all_hospitals"]        = []
        log("📞 Calling emergency contact for test accident (no hospital found)")
        call_success = make_emergency_call(lat, lon, g_force, "unknown, please check maps", 0)
        state["call_made"] = call_success

    state["accident_detected"] = True
    state["g_force"] = round(g_force, 3)
    state["lat"] = lat
    state["lon"] = lon
    state["gps_valid"] = gps_valid
    state["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state()

    return jsonify({
        "accident": True,
        "hospital": state["nearest_hospital"],
        "distance_km": state["distance_km"],
        "hospital_lat": state["nearest_hospital_lat"],
        "hospital_lon": state["nearest_hospital_lon"],
        "all_hospitals": state["all_hospitals"],
        "location": [lat, lon],
        "call_made": state["call_made"]
    }), 200

@app.route("/reset", methods=["POST"])
def reset_system():
    state.update({
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
        "connected"           : False,
        "hardware_id"         : None
    })
    save_state()
    print("✅ System reset.")
    return jsonify({"message": "System reset successful"}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status"          : "ok",
        "json_file_exists": os.path.exists(DATA_FILE),
        "accident_active" : state["accident_detected"],
        "call_made"       : state["call_made"]
    }), 200

if __name__ == "__main__":
    load_state()
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀  G-Trace Flask Server")
    print("    OSM Hospital Search + Twilio Auto Call")
    print(f"   Listening  → http://0.0.0.0:5000")
    print(f"   Data file  → {os.path.abspath(DATA_FILE)}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    app.run(host="0.0.0.0", port=5000, debug=True)


