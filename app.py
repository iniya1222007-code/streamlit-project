import streamlit as st
import pandas as pd
import time
import requests
from datetime import datetime

# =====================================================
# PAGE CONFIG
# =====================================================
st.set_page_config(
    page_title="G-Trace: Emergency Rescue",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================
# BACKEND URL
# Reads from Streamlit secrets on cloud, falls back to localhost
# =====================================================
try:
    BACKEND = st.secrets["BACKEND_URL"].rstrip("/")
except Exception:
    BACKEND = "http://localhost:5000"

STATUS_URL = f"{BACKEND}/status"
LOGS_URL   = f"{BACKEND}/logs"
RESET_URL  = f"{BACKEND}/reset"
TEST_URL   = f"{BACKEND}/test-accident"

# =====================================================
# DATA HELPERS
# =====================================================
def get_state():
    """Fetch live system state from Flask backend."""
    try:
        r = requests.get(STATUS_URL, timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def get_logs():
    """Fetch recent logs from Flask backend."""
    try:
        r = requests.get(LOGS_URL, timeout=3)
        if r.status_code == 200:
            return r.json().get("logs", [])
    except Exception:
        pass
    return []

def reset_backend():
    try:
        requests.post(RESET_URL, timeout=3)
    except Exception:
        pass

def trigger_test():
    try:
        r = requests.post(TEST_URL, json={"lat": 11.0830, "lon": 77.0210}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False

def eta(distance_km, speed_kmh):
    return round((distance_km / max(speed_kmh, 1)) * 60, 1)

# =====================================================
# STYLING
# =====================================================
st.markdown("""
<style>
/* Metric cards */
div[data-testid="metric-container"] {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 16px 20px;
}
/* Pulsing red banner */
.alert-banner {
    background: linear-gradient(135deg, #b30000, #ff1a1a);
    color: white;
    padding: 18px 24px;
    border-radius: 12px;
    text-align: center;
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
    animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.65; }
}
.normal-banner {
    background: linear-gradient(135deg, #006400, #00a000);
    color: white;
    padding: 14px 24px;
    border-radius: 12px;
    text-align: center;
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 8px;
}
</style>
""", unsafe_allow_html=True)

# =====================================================
# SIDEBAR
# =====================================================
st.sidebar.title("🚨 G-Trace")
st.sidebar.caption("Smart Accident Detection & Rescue")
st.sidebar.divider()

# Backend connection indicator
hw = get_state()
backend_up = hw is not None
hw_connected = hw.get("connected", False) if hw else False

if backend_up:
    st.sidebar.success("🟢 Backend Online")
else:
    st.sidebar.error("🔴 Backend Offline")

if hw_connected:
    st.sidebar.success("🟢 ESP32 Hardware Connected")
    hw_id = hw.get("hardware_id", "Unknown")
    st.sidebar.caption(f"Device: {hw_id}")
else:
    st.sidebar.warning("🟡 Hardware Not Connected")
    st.sidebar.caption("Running in simulation mode")

st.sidebar.divider()
st.sidebar.subheader("⚙️ Controls")

amb_speed = st.sidebar.slider("Ambulance Speed (km/h)", 20, 120, 60)

st.sidebar.divider()

# Test & Reset buttons
c1, c2 = st.sidebar.columns(2)
with c1:
    if st.button("🧪 Test", use_container_width=True, help="Fire a mock accident via backend"):
        with st.spinner("Triggering test..."):
            ok = trigger_test()
        if ok:
            st.sidebar.success("Test fired!")
            time.sleep(0.5)
            st.rerun()
        else:
            st.sidebar.error("Backend offline")
with c2:
    if st.button("🔄 Reset", use_container_width=True, help="Reset accident state"):
        reset_backend()
        st.session_state.clear()
        st.sidebar.success("Reset!")
        time.sleep(0.5)
        st.rerun()

st.sidebar.divider()
st.sidebar.caption("G-Trace | PyExpo 2026 | Team PY26069")

# =====================================================
# DETERMINE STATE
# =====================================================
# Real accident from hardware
is_hw_accident = hw.get("accident_detected", False) if hw else False
accident_detected = is_hw_accident

# Pick display data
if hw and accident_detected:
    display = hw
else:
    display = None

current_g   = hw.get("g_force", 0.0) if hw else 0.0
current_lat = hw.get("lat")          if hw else None
current_lon = hw.get("lon")          if hw else None

# =====================================================
# NORMAL STATE — monitoring
# =====================================================
if not accident_detected:
    st.markdown('<div class="normal-banner">✅ &nbsp; ALL SYSTEMS NORMAL — MONITORING ACTIVE</div>', unsafe_allow_html=True)
    st.title("🚗 G-Trace: Real-Time Vehicle Monitoring")
    st.divider()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Live G-Force", f"{current_g:.2f} g", "Normal range")
    with c2:
        st.metric("System Status", "Monitoring", "Active")
    with c3:
        hw_label = "Connected ✅" if hw_connected else "Simulation Mode"
        st.metric("Hardware", hw_label)

    st.divider()
    st.subheader("📍 Live Vehicle Location")

    # Use real GPS if available, else default to Coimbatore
    map_lat = current_lat if current_lat else 11.0168
    map_lon = current_lon if current_lon else 76.9558

    st.map(pd.DataFrame({"lat": [map_lat], "lon": [map_lon]}), zoom=13)

    if hw_connected:
        gps_ok = hw.get("gps_valid", False)
        if gps_ok:
            st.success(f"📡 GPS locked — {map_lat:.5f}, {map_lon:.5f}")
        else:
            st.warning("📡 GPS searching for fix — showing estimated location")
    else:
        st.info("💡 Connect ESP32 hardware, or click **🧪 Test** in the sidebar to simulate an accident.")

# =====================================================
# ACCIDENT STATE — emergency response
# =====================================================
else:
    st.markdown('<div class="alert-banner">🚨 &nbsp; CRITICAL ACCIDENT DETECTED — EMERGENCY RESPONSE ACTIVE &nbsp; 🚨</div>', unsafe_allow_html=True)
    st.title("🚑 G-Trace: Emergency Response")
    st.divider()

    acc_lat  = display.get("lat")                 or 11.0830
    acc_lon  = display.get("lon")                 or 77.0210
    hosp_lat = display.get("nearest_hospital_lat")
    hosp_lon = display.get("nearest_hospital_lon")
    hospital = display.get("nearest_hospital",    "Locating...")
    dist_km  = display.get("distance_km",         0.0)
    ts       = display.get("timestamp",           "N/A")
    call_ok  = display.get("call_made",           False)
    gps_ok   = display.get("gps_valid",           False)

    col_map, col_timeline = st.columns([3, 1])

    # ── LEFT: Map + hospital info ──
    with col_map:
        st.subheader("🗺️ Rescue Route")
        map_points = [{"lat": acc_lat, "lon": acc_lon}]
        if hosp_lat and hosp_lon:
            map_points.append({"lat": hosp_lat, "lon": hosp_lon})
        st.map(pd.DataFrame(map_points), zoom=12)

        st.divider()
        st.subheader("🏥 Hospital Dispatch")
        ca, cb, cc = st.columns(3)
        with ca:
            st.metric("Nearest Hospital", hospital)
        with cb:
            st.metric("Distance", f"{dist_km:.1f} km")
        with cc:
            st.metric("Ambulance ETA", f"{eta(dist_km, amb_speed)} mins")

        # Google Maps link
        maps_url = f"https://maps.google.com/?q={acc_lat},{acc_lon}"
        st.markdown(f"📍 [Open accident location in Google Maps]({maps_url})")

        # All nearby hospitals
        all_hospitals = display.get("all_hospitals", [])
        if len(all_hospitals) > 1:
            with st.expander(f"📋 All {len(all_hospitals)} nearby hospitals"):
                for h in all_hospitals:
                    st.write(f"• {h}")

    # ── RIGHT: Timeline ──
    with col_timeline:
        st.subheader("📢 Emergency Timeline")

        call_label = "✅ Call placed" if call_ok else "⏳ Calling..."
        with st.status("🚨 RESCUE IN PROGRESS", expanded=True, state="running"):
            st.write(f"✅ Impact detected: **{current_g:.1f} g**")
            st.write(f"✅ GPS: **{'Locked' if gps_ok else 'Estimated'}**")
            st.write(f"✅ Hospital found: **{hospital}**")
            st.write(f"✅ Ambulance dispatched")
            st.write(f"📞 Emergency call: **{call_label}**")
            st.write(f"🚦 Traffic priority: **ACTIVE**")

        st.divider()
        st.subheader("📡 Incident Details")
        st.metric("Impact Force", f"{current_g:.2f} g")
        st.write(f"**Time:** {ts}")
        st.write(f"**Coords:** {acc_lat:.4f}, {acc_lon:.4f}")

# =====================================================
# LIVE LOGS (collapsed by default)
# =====================================================
st.divider()
with st.expander("📋 Live System Logs", expanded=False):
    logs = get_logs()
    if logs:
        st.code("\n".join(logs[-30:]), language="text")
    else:
        st.info("No logs yet — system on standby.")

st.caption("👨‍💻 G-Trace AI Emergency System | PyExpo 2026 | Team PY26069")

# =====================================================
# AUTO REFRESH every 2 seconds
# =====================================================
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = datetime.now()

if (datetime.now() - st.session_state.last_refresh).seconds >= 2:
    st.session_state.last_refresh = datetime.now()
    st.rerun()
