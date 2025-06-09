import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO

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

DATA_FILE = "distribution_dashboard_template.xlsx"
settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data(DATA_FILE)

# ————————————————————————————————
# 2. Compute Metrics
# ————————————————————————————————
DAYS = int(settings.loc[settings.Parameter=="Distribution_Days","Value"].iloc[0])
MAX_TRIPS = int(settings.loc[settings.Parameter=="Vehicles_Total","Value"].iloc[0]) \
          * int(settings.loc[settings.Parameter=="Max_Trips_Per_Vehicle_Per_Day","Value"].iloc[0])
TRUCK_CAP = float(settings.loc[settings.Parameter=="Vehicle_Capacity_tons","Value"].iloc[0])

# Daily dispatch totals
day_totals_cg = (dispatch_cg
    .groupby("Dispatch_Day")["Quantity_tons"]
    .sum().reset_index().rename(columns={"Dispatch_Day":"Day"}))
day_totals_lg = (dispatch_lg
    .groupby("Day")["Quantity_tons"]
    .sum().reset_index())

# Vehicle utilization
veh_usage = (dispatch_lg
    .groupby("Day")["Vehicle_ID"]
    .nunique().reset_index(name="Trips_Used"))
veh_usage["Max_Trips"] = MAX_TRIPS

# LG stock time series
lg_stock = (stock_levels[stock_levels.Entity_Type=="LG"]
    .pivot(index="Day", columns="Entity_ID", values="Stock_Level_tons")
    .fillna(method="ffill"))

# FPS at‐risk
fps_stock = (stock_levels[stock_levels.Entity_Type=="FPS"]
    .merge(fps[["FPS_ID","Reorder_Threshold_tons"]],
           left_on="Entity_ID", right_on="FPS_ID"))
fps_stock["At_Risk"] = fps_stock.Stock_Level_tons <= fps_stock.Reorder_Threshold_tons
risk_count = fps_stock.groupby("Day")["At_Risk"].sum().reset_index(name="FPS_At_Risk")

# Flow data for Sankey (CG→LG→FPS)
# Aggregate total flows
cg_lg_flow = dispatch_cg.groupby("LG_ID")["Quantity_tons"].sum().reset_index()
lg_fps_flow = dispatch_lg.groupby(["LG_ID","FPS_ID"])["Quantity_tons"].sum().reset_index()

# ————————————————————————————————
# 3. Build Streamlit Layout
# ————————————————————————————————
st.set_page_config(layout="wide", page_title="Grain Distribution Dashboard")
st.title("🚛 Grain Distribution Dashboard")

# Sidebar – Filters & KPIs
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Day Range", 1, DAYS, (1, DAYS))
    lg_options = list(lg_stock.columns)
    selected_lgs = st.multiselect("Select LGs", options=lg_options, default=lg_options)
    fps_options = fps.FPS_ID.unique().tolist()
    selected_fps = st.multiselect("Select FPS", options=fps_options, default=fps_options)
    st.markdown("---")
    st.header("Key KPIs")
    total_cg = day_totals_cg[(day_totals_cg.Day.between(*day_range))]["Quantity_tons"].sum()
    total_lg = day_totals_lg[(day_totals_lg.Day.between(*day_range))]["Quantity_tons"].sum()
    col1, col2 = st.columns(2)
    col1.metric("CG→LG Dispatched", f"{total_cg:,.1f} t")
    col2.metric("LG→FPS Dispatched", f"{total_lg:,.1f} t")
    st.metric("Max Trucks/Day", f"{MAX_TRIPS}")
    st.metric("Truck Cap", f"{TRUCK_CAP} t")

# ————————————————————————————————
# 4. Top Row: Dispatch Trends
# ————————————————————————————————
col1, col2 = st.columns(2)
with col1:
    st.subheader("CG → LG Dispatch")
    df1 = day_totals_cg[day_totals_cg.Day.between(*day_range)]
    fig1 = px.line(df1, x="Day", y="Quantity_tons",
                   labels={"Quantity_tons":"Tons"}, markers=True)
    st.plotly_chart(fig1, use_container_width=True)

with col2:
    st.subheader("LG → FPS Dispatch")
    df2 = day_totals_lg[day_totals_lg.Day.between(*day_range)]
    fig2 = px.line(df2, x="Day", y="Quantity_tons",
                   labels={"Quantity_tons":"Tons"}, markers=True)
    st.plotly_chart(fig2, use_container_width=True)

# ————————————————————————————————
# 5. Second Row: Vehicle & Stock
# ————————————————————————————————
col3, col4 = st.columns(2)
with col3:
    st.subheader("Vehicle Utilization (LG→FPS)")
    vu = veh_usage[veh_usage.Day.between(*day_range)]
    fig3 = px.area(vu, x="Day", y=["Trips_Used","Max_Trips"],
                   labels={"value":"Trips","variable":"Metric"})
    st.plotly_chart(fig3, use_container_width=True)

with col4:
    st.subheader("LG Stock Levels")
    stock_slice = lg_stock.loc[day_range[0]:day_range[1], selected_lgs]
    fig4 = px.line(stock_slice, labels={"value":"Stock (t)","Day":"Day"})
    st.plotly_chart(fig4, use_container_width=True)

# ————————————————————————————————
# 6. Third Row: At‐Risk & Efficiency
# ————————————————————————————————
col5, col6 = st.columns(2)
with col5:
    st.subheader("FPS At‐Risk Count")
    rc = risk_count[risk_count.Day.between(*day_range)]
    fig5 = px.bar(rc, x="Day", y="FPS_At_Risk")
    st.plotly_chart(fig5, use_container_width=True)

with col6:
    st.subheader("Efficiency Metrics")
    # Calculate Load Factor and Trips per Ton
    load_factor = total_lg / (sum(vu.Trips_Used) * TRUCK_CAP) if vu.Trips_Used.sum()>0 else 0
    t_per_ton = sum(vu.Trips_Used) / total_lg if total_lg>0 else 0
    st.metric("Avg Load Factor", f"{load_factor:.2%}")
    st.metric("Trips per Ton", f"{t_per_ton:.4f}")

# ————————————————————————————————
# 7. Sankey Flow Diagram (fixed)
# ————————————————————————————————
import plotly.graph_objects as go

st.subheader("Flow Sankey: CG → LG → FPS")

# 1) Unique ordered node lists
lg_nodes  = cg_lg_flow["LG_ID"].astype(str).unique().tolist()
fps_nodes = lg_fps_flow["FPS_ID"].astype(str).unique().tolist()
nodes     = ["CG"] + lg_nodes + fps_nodes

# 2) Build index mapping
idx = {node: i for i, node in enumerate(nodes)}

# 3) Build raw link dicts
raw_links = []
for _, row in cg_lg_flow.iterrows():
    raw_links.append({
        "source": idx["CG"],
        "target": idx[str(int(row.LG_ID))],
        "value":  row.Quantity_tons
    })
for _, row in lg_fps_flow.iterrows():
    raw_links.append({
        "source": idx[str(int(row.LG_ID))],
        "target": idx[str(int(row.FPS_ID))],
        "value":  row.Quantity_tons
    })

# 4) Convert to parallel arrays
sources = [l["source"] for l in raw_links]
targets = [l["target"] for l in raw_links]
values  = [l["value"]  for l in raw_links]

# 5) Draw the Sankey
fig_sankey = go.Figure(go.Sankey(
    node=dict(label=nodes, pad=15, thickness=20),
    link=dict(source=sources, target=targets, value=values)
))
st.plotly_chart(fig_sankey, use_container_width=True)

# ————————————————————————————————
# 8. Data Download
# ————————————————————————————————
st.subheader("Download Data")
def to_excel(df):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

dl_cg = to_excel(dispatch_cg)
dl_lg = to_excel(dispatch_lg)
st.download_button("Download CG→LG Dispatch", dl_cg, "cg_to_lg.xlsx")
st.download_button("Download LG→FPS Dispatch", dl_lg, "lg_to_fps.xlsx")
