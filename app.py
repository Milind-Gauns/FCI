import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# 1. Page config (first command)
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")

# 2. Helper to export DataFrame to Excel
def to_excel(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

# 3. Load & cache data
@st.cache_data
def load_data(fn: str):
    settings      = pd.read_excel(fn, sheet_name="Settings")
    dispatch_cg   = pd.read_excel(fn, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg   = pd.read_excel(fn, sheet_name="LG_to_FPS_Dispatch")
    stock_levels  = pd.read_excel(fn, sheet_name="Stock_Levels")
    lgs           = pd.read_excel(fn, sheet_name="LGs")
    fps           = pd.read_excel(fn, sheet_name="FPS")
    # Ensure types
    lgs["LG_ID"]  = lgs["LG_ID"].astype(str)
    fps["FPS_ID"] = fps["FPS_ID"].astype(int)
    fps["FPS_Name"] = fps["FPS_Name"].astype(str)
    return settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps

settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data("distribution_dashboard_output.xlsx")

# 4. Compute core metrics
DAYS      = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
DAILY_CAP = MAX_TRIPS * TRUCK_CAP

# Pre-dispatch offset X
dt = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum()
cum = 0; adv = []
for d in range(1, DAYS+1):
    cum += dt.get(d, 0)
    over = (cum - DAILY_CAP * d) / DAILY_CAP
    adv.append(math.ceil(over) if over > 0 else 0)
X = max(adv)
MIN_DAY = 1 - X
MAX_DAY = DAYS

# Summaries
day_totals_cg = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum().reset_index().rename(columns={"Dispatch_Day":"Day"})
day_totals_lg = dispatch_lg.groupby("Day")["Quantity_tons"].sum().reset_index()
veh_usage     = dispatch_lg.groupby("Day")["Vehicle_ID"].nunique().reset_index(name="Trips_Used")
veh_usage["Max_Trips"] = MAX_TRIPS
lg_stock      = stock_levels[stock_levels.Entity_Type=="LG"].pivot(index="Day", columns="Entity_ID", values="Stock_Level_tons").fillna(method="ffill")

# FPS stock & at-risk
fps_stock     = stock_levels[stock_levels.Entity_Type=="FPS"]\
                .rename(columns={"Entity_ID":"FPS_ID"})
fps_stock["At_Risk"] = fps_stock["Stock_Level_tons"] <= fps_stock["Reorder_Threshold_tons"]

total_plan = day_totals_lg.Quantity_tons.sum()

# 5. Sidebar filters & KPIs
st.title("🚛 Grain Distribution Dashboard")
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Dispatch Window (days)", MIN_DAY, MAX_DAY, (MIN_DAY, MAX_DAY), format="%d")
    st.subheader("Select LGs")
    cols     = st.columns(4)
    lg_ids   = lgs["LG_ID"].tolist()
    lg_names = lgs["LG_Name"].tolist()
    selected_lgs = []
    for i, name in enumerate(lg_names):
        if cols[i % 4].checkbox(name, True, key=f"lg_{i}"):
            selected_lgs.append(int(lg_ids[i]))
    st.markdown("---")
    st.header("Quick KPIs")
    cg_sel = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    lg_sel = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")["Quantity_tons"].sum()
    st.metric("CG→LG Total (t)", f"{cg_sel:,.1f}")
    st.metric("LG→FPS Total (t)", f"{lg_sel:,.1f}")
    st.metric("Max Trucks/Day",   f"{MAX_TRIPS}")
    st.metric("Truck Capacity (t)", f"{TRUCK_CAP}")

# 6. CG→LG Overview
st.subheader("CG → LG Dispatch")
df1 = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")
fig1 = px.bar(df1, x="Day", y="Quantity_tons", text="Quantity_tons")
fig1.update_traces(texttemplate="%{text:.1f}t", textposition="outside")
st.plotly_chart(fig1, use_container_width=True)

# 7. LG→FPS Overview
st.subheader("LG → FPS Dispatch")
df2 = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")
fig2 = px.bar(df2, x="Day", y="Quantity_tons", text="Quantity_tons")
fig2.update_traces(texttemplate="%{text:.1f}t", textposition="outside")
st.plotly_chart(fig2, use_container_width=True)

# 8. FPS Report
st.subheader("FPS-wise Dispatch Details")
fps_df = dispatch_lg.query("Day>=1 & Day<=@day_range[1] & LG_ID in @selected_lgs")
report = (
    fps_df.groupby("FPS_ID")
    .agg(
        Total_Dispatched_tons=pd.NamedAgg("Quantity_tons","sum"),
        Trips_Count=pd.NamedAgg("Vehicle_ID","
