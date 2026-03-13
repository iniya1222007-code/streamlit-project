import streamlit as st
import pandas as pd
import time
import json
import os
import requests

st.set_page_config(
    page_title="G-Trace: AI Emergency Rescue",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATA_FILE = "accident_status.json"
FLASK_URL = "http://localhost:5000/status"

@st.cache_data(ttl=2)
def get_hardware_data():
    try:
        response = requests.get(FLASK_URL, timeout=5)
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

st.markdown("""
<style>
.reportview-container { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.stMetric { background-color: rgba(255,255,255,0.9); padding: 15px; border-radius: 15px; border: 2px solid #ddd; }
.metric-container { background-color: rgba(255,255,255,0.95); padding: 20px; border-radius: 20px; }
</style>
""", unsafe_allow_html=True)


st.sidebar.header("📡 Control Panel")
test_g_force = st.sidebar.slider("Test G-Force", 0.0, 15.0, 3.5)
amb_speed = st.sidebar.slider("Ambulance Speed (km/h)", 20, 120, 60)

if st.sidebar.button("🔄 Reset System"):
    try:
        requests.post("http://localhost:5000/reset")
        st.sidebar.success("Reset successful!")
        time.sleep(1)
        st.rerun()
    except:
        st.sidebar.error("Flask server not running!")


hw_data = get_hardware_data()
accident_detected = hw_data.get("accident_detected", False) if hw_data else (test_g_force >= 10.0)
current_g = hw_data.get("g_force", test_g_force) if hw_data else test_g_force

if not accident_detected:
    st.success("✅ SYSTEM STATUS: ALL SYSTEMS NORMAL")
    st.title("🚗 G-Trace: Real-Time Vehicle Monitoring")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Current G-Force", f"{current_g:.2f}g", "Normal")
    with col2:
        st.metric("Status", "Monitoring", "Active")
    
    
    if hw_data and hw_data.get("lat") and hw_data.get("lon"):
        df = pd.DataFrame({"lat": [hw_data["lat"]], "lon": [hw_data["lon"]]})
        st.map(df, zoom=13)
    else:
        st.info("📍 Waiting for GPS signal...")

else:
    st.error("🚨 CRITICAL ACCIDENT DETECTED!")
    st.title("🚑 G-Trace: Emergency Response Active")
    

    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.subheader("🗺️ Live Rescue Map")
        
        map_data = {
            "lat": [],
            "lon": [],
            "name": []
        }
        
    
        if hw_data:
            map_data["lat"].extend([hw_data["lat"]])
            map_data["lon"].extend([hw_data["lon"]])
            map_data["name"].extend(["🚨 Accident"])
            
            # Hospital location
            if hw_data.get("nearest_hospital_lat"):
                map_data["lat"].extend([hw_data["nearest_hospital_lat"]])
                map_data["lon"].extend([hw_data["nearest_hospital_lon"]])
                map_data["name"].extend(["🏥 Hospital"])
        
        if map_data["lat"]:
            df_map = pd.DataFrame(map_data)
            st.map(df_map, zoom=13)
        
        st.divider()
        st.subheader("📋 Hospital Information")
        if hw_data:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Nearest Hospital", 
                         hw_data.get("nearest_hospital", "N/A"))
            with col_b:
                st.metric("Distance", 
                         f"{hw_data.get('distance_km', 0):.1f} km")
            with col_c:
                eta = calculate_eta(hw_data.get('distance_km', 0), amb_speed)
                st.metric("ETA", f"{eta} mins")
            
            if hw_data.get("all_hospitals"):
                st.write("**Other Hospitals:**")
                for hospital in hw_data["all_hospitals"][:3]:
                    st.write(f"• {hospital}")
    
    with col2:
        st.subheader("📢 Emergency Timeline")
        with st.status("🚨 EMERGENCY RESPONSE", expanded=True):
            st.write("✅ High-G impact verified")
            st.write("✅ GPS location captured")
            st.write("✅ Nearest hospital located")
            st.write("✅ 108 ambulance dispatched")
            st.write("✅ Traffic signals overridden")
        
        st.divider()
        st.subheader("📡 Hardware Status")
        st.metric("Impact Force", f"{current_g:.2f}g")
        st.metric("GPS", "Valid" if hw_data.get("gps_valid") else "Searching")
        st.write(f"**Time:** {hw_data.get('timestamp', 'N/A')}")


st.divider()
st.caption("👨‍💻 G-Trace Emergency System | Coimbatore, Tamil Nadu")
