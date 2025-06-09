import streamlit as st
import pandas as pd
import plotly.express as px

# ————————————————————————————————
# 1. Load & Cache Data
# ————————————————————————————————
@st.cache_data
def load_data(fn):
    settings     = pd.read_excel(fn, sheet_name="Settings")
    dispatch_cg  = pd.read_excel(fn, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg  = pd.read_excel(fn, sheet_name="LG_to_FPS_Dispatch")
    stock_levels = pd.read_excel(fn, sheet_name="Stock_Levels")
    lgs          = pd.read_excel(fn, sheet_name="LGs")
    fps          = pd.read_excel(fn, sheet_name="FPS")
    return settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps

DATA_FILE = "distribution_dashboard_output.xlsx"
settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data(DATA_FILE)

# ————————————————————————————————
# 2. Prepare Metrics
# ————————————————————————————————
DAYS = int(settings.loc[settings.Parameter=="Distribution_Days","Value"].iloc[0])

# CG → LG per-day totals
day_totals_cg = (
    dispatch_cg
    .groupby("Dispatch_Day")["Quantity_tons"]
    .sum()
    .reset_index()
    .rename(columns={"Dispatch_Day":"Day"})
)

# LG → FPS per-day totals
day_totals_lg = (
    dispatch_lg
    .groupby("Day")["Quantity_tons"]
    .sum()
    .reset_index()
)

# Vehicle utilization (unique vehicles per LG→FPS day)
veh_usage = (
    dispatch_lg
    .groupby("Day")["Vehicle_ID"]
    .nunique()
    .reset_index(name="Trips_Used")
)
max_trips = (
    int(settings.loc[settings.Parameter=="Vehicles_Total","Value"].iloc[0]) *
    int(settings.loc[settings.Parameter=="Max_Trips_Per_Vehicle_Per_Day","Value"].iloc[0])
)
veh_usage["Max_Trips"] = max_trips

# LG stock time series
lg_stock = (
    stock_levels[stock_levels.Entity_Type=="LG"]
    .pivot(index="Day", columns="Entity_ID", values="Stock_Level_tons")
    .fillna(method="ffill")
)

# FPS at-risk counts
fps_stock = (
    stock_levels[stock_levels.Entity_Type=="FPS"]
    .merge(fps[["FPS_ID","Reorder_Threshold_tons"]],
           left_on="Entity_ID", right_on="FPS_ID")
)
fps_stock["At_Risk"] = fps_stock.Stock_Level_tons <= fps_stock.Reorder_Threshold_tons
risk_count = fps_stock.groupby("Day")["At_Risk"].sum().reset_index(name="FPS_At_Risk")

# ————————————————————————————————
# 3. Build Streamlit UI
# ————————————————————————————————
st.set_page_config(layout="wide", page_title="Grain Distribution Dashboard")
st.title("Grain Distribution Dashboard")

# Sidebar filters
st.sidebar.header("Filters")
day_range = st.sidebar.slider("Day Range", 1, DAYS, (1, DAYS))
selected_lgs = st.sidebar.multiselect(
    "Select LG(s)", 
    options=lg_stock.columns.tolist(),
    default=lg_stock.columns.tolist()
)
st.sidebar.markdown("---")

# ————————————————————————————————
# 4. Render Charts
# ————————————————————————————————
# CG → LG Dispatch
st.subheader("CG → LG Dispatch (Tons per Day)")
df_cg = day_totals_cg[
    (day_totals_cg.Day >= day_range[0]) &
    (day_totals_cg.Day <= day_range[1])
]
st.plotly_chart(
    px.bar(df_cg, x="Day", y="Quantity_tons", labels={"Quantity_tons":"Tons"}),
    use_container_width=True
)

# LG → FPS Dispatch
st.subheader("LG → FPS Dispatch (Tons per Day)")
df_lg = day_totals_lg[
    (day_totals_lg.Day >= day_range[0]) &
    (day_totals_lg.Day <= day_range[1])
]
st.plotly_chart(
    px.bar(df_lg, x="Day", y="Quantity_tons", labels={"Quantity_tons":"Tons"}),
    use_container_width=True
)

# Vehicle Utilization
st.subheader("Vehicle Utilization (LG → FPS)")
vu = veh_usage[
    (veh_usage.Day >= day_range[0]) &
    (veh_usage.Day <= day_range[1])
]
st.plotly_chart(
    px.line(vu, x="Day", y=["Trips_Used","Max_Trips"], 
            labels={"value":"Trips","variable":"Metric"}),
    use_container_width=True
)

# LG Stock Levels
st.subheader("LG Stock Levels Over Time")
stock_slice = lg_stock.loc[day_range[0]:day_range[1], selected_lgs]
st.line_chart(stock_slice)

# FPS At-Risk
st.subheader("FPS At-Risk Count")
rc = risk_count[
    (risk_count.Day >= day_range[0]) &
    (risk_count.Day <= day_range[1])
]
st.bar_chart(rc.set_index("Day")["FPS_At_Risk"])
