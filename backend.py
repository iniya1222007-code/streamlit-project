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

# ===== CONFIGURATION =====
TWILIO_SID   = "ENTER TWILIO SID"
TWILIO_TOKEN = "ENTER TWILIO TOKEN"
TWILIO_FROM  = "+13502503782" 
CALL_TO      = "+918220387221"

DATA_FILE = "accident_status.json"
logs_list = []
MAX_LOGS = 100

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

# ===== UTILITIES =====
def log_output(message):
    """Custom logging function to capture output."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    logs_list.append(log_entry)
    if len(logs_list) > MAX_LOGS:
        logs_list.pop(0)
    print(log_entry)

def save_state():
    with open(DATA_FILE, "w") as f:
        json.dump(state, f, indent=2)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ===== EMERGENCY SERVICES =====
def make_emergency_call(lat, lon, g_force, hospital_name, distance_km):
    if not TWILIO_SID or not TWILIO_TOKEN:
        log_output(f"MOCK CALL (Missing Creds): {hospital_name}")
        return True
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        twiml_message = f"""
        <Response>
            <Say voice="alice" loop="2">
                Emergency Alert from G Trace System. Vehicle accident detected.
                Impact severity {g_force} G force. Location {lat} latitude, {lon} longitude.
                Nearest hospital is {hospital_name}, approximately {distance_km} kilometers away.
                Please dispatch ambulance immediately.
            </Say>
        </Response>
        """
        call = client.calls.create(twiml=twiml_message, to=CALL_TO, from_=TWILIO_FROM)
        log_output(f"REAL Emergency call made! SID: {call.sid}")
        return True
    except Exception as e:
        log_output(f"Twilio call error: {e}")
        return False

def osm_find_hospitals(lat, lon, radius_meters=5000):
    log_output(f"OSM query: {radius_meters}m around ({lat},{lon})")
    overpass_query = f"""
    [out:json][timeout:25];
    (node["amenity"="hospital"](around:{radius_meters},{lat},{lon});
     way["amenity"="hospital"](around:{radius_meters},{lat},{lon});
     node["amenity"="clinic"](around:{radius_meters},{lat},{lon}););
    out center;
    """
    try:
        response = requests.post("https://overpass-api.de/api/interpreter", data={"data": overpass_query}, timeout=20)
        elements = response.json().get("elements", [])
        hospitals = []
        for el in elements:
            h_lat = el.get("lat") or el.get("center", {}).get("lat")
            h_lon = el.get("lon") or el.get("center", {}).get("lon")
            name = el.get("tags", {}).get("name", "Unnamed Hospital")
            if h_lat and h_lon:
                dist = haversine(lat, lon, float(h_lat), float(h_lon))
                hospitals.append({"name": name, "lat": float(h_lat), "lon": float(h_lon), "dist": dist})
        
        if not hospitals and radius_meters < 15000:
            return osm_find_hospitals(lat, lon, radius_meters + 5000)
        
        if hospitals:
            hospitals.sort(key=lambda h: h["dist"])
            nearest = hospitals[0]
            all_names = [f"{h['name']} ({round(h['dist'], 1)} km)" for h in hospitals]
            return nearest["name"], round(nearest["dist"], 2), nearest["lat"], nearest["lon"], all_names
        return None
    except Exception as e:
        log_output(f"OSM error: {e}")
        return None

# ===== ROUTES =====
@app.route("/data", methods=["POST"])
def receive_data():
    try:
        data = request.get_json(force=True)
        g_force = float(data.get("g_force", 0))
        p_lat = float(data.get("lat", 11.0830))
        p_lon = float(data.get("lon", 77.0210))
        gps_valid = bool(data.get("gps_valid", False))

        state.update({
            "g_force": round(g_force, 3), "lat": p_lat, "lon": p_lon, "gps_valid": gps_valid,
            "hardware_id": data.get("hardware_id", "unknown"),
            "last_ping": datetime.now().isoformat(), "connected": True
        })

        log_output(f"Received: G={g_force:.2f} | GPS={'valid' if gps_valid else 'estimated'}")

        accident_override = data.get("accident", False)

        # TRIGGER LOGIC
        if g_force > 1.0 or accident_override:
            state["accident_detected"] = True
            state["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            log_output(f"🚨 ACCIDENT DETECTED! G-Force: {g_force}")
            
            result = osm_find_hospitals(p_lat, p_lon)
            if result:
                state["nearest_hospital"], state["distance_km"], state["nearest_hospital_lat"], state["nearest_hospital_lon"], state["all_hospitals"] = result
            else:
                state["nearest_hospital"] = "KMCH Hospital (Demo Fallback)"
                state["distance_km"] = 4.2

            call_success = make_emergency_call(p_lat, p_lon, g_force, state["nearest_hospital"], state["distance_km"])
            state["call_made"] = call_success
            
            save_state()
            return jsonify({"accident": True, "hospital": state["nearest_hospital"], "call_made": call_success}), 200

        save_state()
        return jsonify({"accident": False, "g_force": g_force}), 200
    except Exception as e:
        log_output(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/status", methods=["GET"])
def check_status():
    if state["last_ping"]:
        last_ping_dt = datetime.fromisoformat(state["last_ping"])
        state["connected"] = (datetime.now() - last_ping_dt) < timedelta(minutes=5)
    return jsonify(state), 200

@app.route("/reset", methods=["POST"])
def reset_system():
    state.update({"accident_detected": False, "g_force": 0.0, "nearest_hospital": "None", "call_made": False})
    save_state()
    log_output("System reset.")
    return jsonify({"message": "System reset successful"}), 200

@app.route("/logs", methods=["GET"])
def get_logs():
    return jsonify({"logs": logs_list}), 200

@app.route("/test-accident", methods=["POST"])
def test_accident():
    # Simulates a full accident cycle for testing without hardware
    data = request.get_json(force=True) or {}
    return receive_data() # Reuse logic with accident override

@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "G-Trace Backend Active", "status_file": DATA_FILE})

if __name__ == "__main__":
    print("="*50 + "\nG-Trace Server Listening on http://0.0.0.0:5000\n" + "="*50)
    app.run(host="0.0.0.0", port=5000, debug=True)
