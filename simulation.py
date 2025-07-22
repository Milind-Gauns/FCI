import streamlit as st 
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ————————————————————————————————
# 1. Page config
# ————————————————————————————————
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")

# ————————————————————————————————
# 2. Helper to export DataFrame to Excel
# ————————————————————————————————
def to_excel(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

# ————————————————————————————————
# 3. Load & cache defaults (resilient to missing Vehicles sheet)
# ————————————————————————————————
DEFAULT_FILE = "distribution_dashboard_template.xlsx"

@st.cache_data
def load_defaults():
    xlsx = pd.ExcelFile(DEFAULT_FILE)
    settings    = pd.read_excel(xlsx, sheet_name="Settings")
    default_lgs = pd.read_excel(xlsx, sheet_name="LGs")
    default_fps = pd.read_excel(xlsx, sheet_name="FPS")
    # If Vehicles sheet exists, load it; otherwise create empty skeleton
    if "Vehicles" in xlsx.sheet_names:
        default_veh = pd.read_excel(xlsx, sheet_name="Vehicles")
    else:
        default_veh = pd.DataFrame(columns=["Vehicle_ID","Capacity_tons","Mapped_LG_IDs"])
    return settings, default_lgs, default_fps, default_veh

settings, default_lgs, default_fps, default_veh = load_defaults()

# ————————————————————————————————
# 4. Upload / Download Master Data
# ————————————————————————————————
st.sidebar.subheader("📁 Edit Master Data")

def make_excel(dfs: dict) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        for name, df in dfs.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()

# LGs
st.sidebar.markdown("**LGs**")
xls_lg = make_excel({"LGs": default_lgs})
st.sidebar.download_button("Download LGs", xls_lg, "LGs.xlsx", 
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
up = st.sidebar.file_uploader("Upload LGs", type=["xlsx","csv"], key="lg_upload")
if up:
    lgs = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up, sheet_name="LGs")
else:
    lgs = default_lgs.copy()

# FPS
st.sidebar.markdown("**FPS**")
xls_fps = make_excel({"FPS": default_fps})
st.sidebar.download_button("Download FPS", xls_fps, "FPS.xlsx", 
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
up = st.sidebar.file_uploader("Upload FPS", type=["xlsx","csv"], key="fps_upload")
if up:
    fps = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up, sheet_name="FPS")
else:
    fps = default_fps.copy()

# Vehicles
st.sidebar.markdown("**Vehicles**")
xls_veh = make_excel({"Vehicles": default_veh})
st.sidebar.download_button("Download Vehicles", xls_veh, "Vehicles.xlsx", 
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
up = st.sidebar.file_uploader("Upload Vehicles", type=["xlsx","csv"], key="veh_upload")
if up:
    vehicles = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up, sheet_name="Vehicles")
else:
    vehicles = default_veh.copy()

# ————————————————————————————————
# 5. Simulation entry point
# ————————————————————————————————
from simulation import run_simulation  # your algorithm module

dispatch_cg  = pd.DataFrame()
dispatch_lg  = pd.DataFrame()
stock_levels = pd.DataFrame()

if st.sidebar.button("▶️ Run Simulation"):
    with st.spinner("Running simulation…"):
        dispatch_cg, dispatch_lg, stock_levels = run_simulation(
            settings, lgs, fps, vehicles
        )
    st.sidebar.success("Simulation complete!")
else:
    st.sidebar.info("Upload masters and click ▶️ to run.")

# Fallback: if not yet run, load static defaults
if dispatch_lg.empty:
    dispatch_cg  = pd.read_excel(DEFAULT_FILE, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg  = pd.read_excel(DEFAULT_FILE, sheet_name="LG_to_FPS_Dispatch")
    stock_levels = pd.read_excel(DEFAULT_FILE, sheet_name="Stock_Levels")

# ————————————————————————————————
# 6. Dashboard logic
# ————————————————————————————————
# (Insert your existing code here unmodified, referencing
#  dispatch_cg, dispatch_lg, stock_levels, lgs, fps, etc.)

