import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# 1. Page config
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")

# 2. Excel export helper
def to_excel(df):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

# 3. Load & cache data
@st.cache_data
def load_data(fn):
    settings     = pd.read_excel(fn, sheet_name="Settings")
    dispatch_cg  = pd.read_excel(fn, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg  = pd.read_excel(fn, sheet_name="LG_to_FPS_Dispatch")
    stock_levels = pd.read_excel(fn, sheet_name="Stock_Levels")
    lgs          = pd.read_excel(fn, sheet_name="LGs")
    fps          = pd.read_excel(fn, sheet_name="FPS")
    return settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps

settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data("distribution_dashboard_template.xlsx")

# 4. Core metrics (unchanged from before)...
DAYS      = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
DAILY_CAP = MAX_TRIPS * TRUCK_CAP

dt = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum()
cum = 0; adv = []
for d in range(1, DAYS+1):
    cum += dt.get(d,0)
    over = (cum - DAILY_CAP*d)/DAILY_CAP
    adv.append(math.ceil(over) if over>0 else 0)
X = max(adv); MIN_DAY=1-X; MAX_DAY=DAYS

day_totals_cg = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum().reset_index().rename(columns={"Dispatch_Day":"Day"})
day_totals_lg = dispatch_lg.groupby("Day")["Quantity_tons"].sum().reset_index()
veh_usage     = dispatch_cg.groupby(["Dispatch_Day","LG_ID"])["Vehicle_ID"].nunique().reset_index(name="Trucks_Used").rename(columns={"Dispatch_Day":"Day"})
veh_usage["Max_Trips"] = MAX_TRIPS

# ————————————————————————————————
# **Patch**: Dynamically detect the entity‐type column name
# ————————————————————————————————
entity_col = next(
    col for col in stock_levels.columns
    if col.lower().replace("_"," ").strip() == "entity type"
)

lg_stock = (
    stock_levels[stock_levels[entity_col] == "LG"]
    .pivot_table(index="Day", columns="Entity_ID", values="Stock_Level_tons", aggfunc="first")
    .fillna(method="ffill")
)

fps_stock = (
    stock_levels[stock_levels[entity_col] == "FPS"]
    .rename(columns={"Entity_ID":"FPS_ID"})
    .merge(fps[["FPS_ID","Reorder_Threshold_tons"]], on="FPS_ID", how="left")
)
fps_stock["At_Risk"] = fps_stock["Stock_Level_tons"] <= fps_stock["Reorder_Threshold_tons"]

total_plan = day_totals_lg.Quantity_tons.sum()

# 5. Sidebar & Tabs (unchanged structure)…
st.title("🚛 Grain Distribution Dashboard")
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Dispatch Window", MIN_DAY, MAX_DAY, (MIN_DAY,MAX_DAY), format="%d")
    st.subheader("Select LGs")
    cols = st.columns(4)
    lg_ids = lgs["LG_ID"].astype(str).tolist()
    lg_names = lgs["LG_Name"].tolist()
    selected_lgs = []
    for i,name in enumerate(lg_names):
        if cols[i%4].checkbox(name, True, key=f"lg_{i}"):
            selected_lgs.append(int(lg_ids[i]))
    st.markdown("---")
    cg_sel = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    lg_sel = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")["Quantity_tons"].sum()
    st.header("Quick KPIs")
    st.metric("CG→LG Total (t)", f"{cg_sel:,.1f}")
    st.metric("LG→FPS Total (t)", f"{lg_sel:,.1f}")
    st.metric("Max Trucks/Day", f"{MAX_TRIPS}")
    st.metric("Truck Capacity (t)", f"{TRUCK_CAP}")

tab1,tab2,tab3,tab4,tab5,tab6,tab7 = st.tabs([
    "CG→LG Overview","LG→FPS Overview","FPS Report",
    "FPS At-Risk","FPS Data","Downloads","Metrics"
])

# 6–13. All your existing tab code goes here **unchanged**,**
# only the lg_stock and fps_stock definitions above have been patched.
