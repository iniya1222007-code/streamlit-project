import streamlit as st
import pandas as pd
import time
import json
import os
import requests
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(
    page_title="G-Trace: AI Emergency Rescue",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Use /tmp/ for cloud deployment compatibility
DATA_FILE = "/tmp/accident_status.json"
FLASK_URL = "http://localhost:5000/status"

# --- HELPER FUNCTIONS ---
def get_hardware_data():
    """Tries to get real data from Flask, then local file, otherwise returns None."""
    try:
        # This will only work if your Flask server is running on the same machine
        response = requests.get(FLASK_URL, timeout=1)
        return response.json() if response.status_code == 200 else None
    except:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
    return None

def calculate_eta(distance_km, amb_speed=60):
    return round((distance_km / max(amb_speed, 1)) * 60, 1)

# --- STYLING ---
st.markdown("""
<style>
.stMetric { background-color: rgba(255,255,255,0.1); padding: 15px; border-radius: 15px; border: 1px solid #444; }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR CONTROL PANEL ---
st.sidebar.header("📡 Control Panel")
test_g_force = st.sidebar.slider("Test G-Force (Simulate Impact)", 0.0, 15.0, 3.5)
amb_speed = st.sidebar.slider("Ambulance Speed (km/h)", 20, 120, 60)

if st.sidebar.button("🔄 Reset System"):
    # If on local, try to reset Flask. If on cloud, just clear session.
    st.session_state.clear()
    st.sidebar.success("System Reset!")
    time.sleep(1)
    st.rerun()

# --- DATA PROCESSING ---
hw_data = get_hardware_data()

# Logic: If slider is high OR hardware says accident, trigger emergency mode
is_test_accident = test_g_force >= 10.0
is_hw_accident = hw_data.get("accident_detected", False) if hw_data else False
accident_detected = is_test_accident or is_hw_accident

current_g = hw_data.get("g_force", test_g_force) if (hw_data and not is_test_accident) else test_g_force

# --- UI LAYOUT ---
if not accident_detected:
    st.success("✅ SYSTEM STATUS: ALL SYSTEMS NORMAL")
    st.title("🚗 G-Trace: Real-Time Vehicle Monitoring")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Current G-Force", f"{current_g:.2f}g", "Normal")
    with col2:
        st.metric("Status", "Monitoring", "Active")
    
    # Default map view (Coimbatore) if no GPS
    default_lat, default_lon = 11.0168, 76.9558
    p_lat = hw_data.get("lat", default_lat) if hw_data else default_lat
    p_lon = hw_data.get("lon", default_lon) if hw_data else default_lon
    
    df = pd.DataFrame({"lat": [p_lat], "lon": [p_lon]})
    st.map(df, zoom=13)
    st.info("📍 System standing by. Increase 'Test G-Force' to 10.0+ to simulate an accident.")

else:
    st.error("🚨 CRITICAL ACCIDENT DETECTED!")
    st.title("🚑 G-Trace: Emergency Response Active")

    # If it's a test/simulated accident, we create fake hospital data
    if is_test_accident and not is_hw_accident:
        display_data = {
            "lat": 11.0830, "lon": 77.0210, # Near KiTE
            "nearest_hospital": "KMCH Hospital",
            "nearest_hospital_lat": 11.0500, "nearest_hospital_lon": 77.0400,
            "distance_km": 4.2,
            "all_hospitals": ["PSG Hospitals (5.1 km)", "Ganga Hospital (8.4 km)"],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "gps_valid": True
        }
    else:
        display_data = hw_data

    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.subheader("🗺️ Live Rescue Map")
        map_points = []
        if display_data:
            map_points.append({"lat": display_data["lat"], "lon": display_data["lon"], "name": "Accident"})
            if display_data.get("nearest_hospital_lat"):
                map_points.append({"lat": display_data["nearest_hospital_lat"], "lon": display_data["nearest_hospital_lon"], "name": "Hospital"})
            
            st.map(pd.DataFrame(map_points), zoom=12)
        
        st.divider()
        st.subheader("📋 Hospital Information")
        if display_data:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Nearest Hospital", display_data.get("nearest_hospital", "N/A"))
            with col_b:
                st.metric("Distance", f"{display_data.get('distance_km', 0):.1f} km")
            with col_c:
                eta = calculate_eta(display_data.get('distance_km', 0), amb_speed)
                st.metric("ETA", f"{eta} mins")
    
    with col2:
        st.subheader("📢 Emergency Timeline")
        with st.status("🚨 RESCUE IN PROGRESS", expanded=True):
            st.write("✅ Impact verified:", f"{current_g}g")
            st.write("✅ Nearest hospital alerted")
            st.write("✅ Dispatching ambulance")
            st.write("⏳ Traffic signal priority: ACTIVE")
        
        st.divider()
        st.subheader("📡 Status")
        st.metric("Impact Force", f"{current_g:.2f}g")
        st.write(f"**Time:** {display_data.get('timestamp', 'N/A')}")

st.divider()
st.caption("👨‍💻 G-Trace AI Emergency System | PyExpo 2026")
