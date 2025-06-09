import streamlit as st
import pandas as pd
import plotly.express as px
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

DATA_FILE = "distribution_dashboard_output.xlsx"
settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data(DATA_FILE)

# ————————————————————————————————
# 2. Compute Metrics
# ————————————————————————————————
DAYS = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * \
            int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])

# Daily totals
day_totals_cg = (dispatch_cg
    .groupby("Dispatch_Day")["Quantity_tons"]
    .sum().reset_index().rename(columns={"Dispatch_Day":"Day"}))
day_totals_lg = (dispatch_lg
    .groupby("Day")["Quantity_tons"]
    .sum().reset_index())

# Vehicle Utilization
veh_usage = (dispatch_lg
    .groupby("Day")["Vehicle_ID"]
    .nunique().reset_index(name="Trips_Used"))
veh_usage["Max_Trips"] = MAX_TRIPS

# LG Stock
lg_stock = (stock_levels[stock_levels.Entity_Type=="LG"]
    .pivot(index="Day", columns="Entity_ID", values="Stock_Level_tons")
    .fillna(method="ffill"))

# FPS Dispatch detail for report
# we'll filter dispatch_lg by day_range later

# ————————————————————————————————
# 3. Page Layout & Filters
# ————————————————————————————————
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")
st.title("🚛 Grain Distribution Dashboard")

# Sidebar filters & KPIs
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Day Range", 1, DAYS, (1, DAYS))
    lg_options = list(lg_stock.columns)
    selected_lgs = st.multiselect("Select LG(s)", options=lg_options, default=lg_options)
    st.markdown("---")
    st.header("Key Metrics")
    metric_col1, metric_col2 = st.columns(2)
    total_cg = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    total_lg = day_totals_lg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    metric_col1.metric("CG→LG Dispatched", f"{total_cg:,.1f} t")
    metric_col2.metric("LG→FPS Dispatched", f"{total_lg:,.1f} t")
    st.metric("Max Trucks/Day", f"{MAX_TRIPS}")
    st.metric("Truck Capacity", f"{TRUCK_CAP} t")

# Use tabs for sections
tab1, tab2 = st.tabs(["Overview", "FPS Report"])

# ————————————————————————————————
# 4. Tab 1: Overview
# ————————————————————————————————
with tab1:
    # Dispatch trends
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("CG → LG Dispatch Trend")
        df1 = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")
        fig1 = px.line(df1, x="Day", y="Quantity_tons",
                       labels={"Quantity_tons":"Tons"}, markers=True)
        st.plotly_chart(fig1, use_container_width=True)
    with col2:
        st.subheader("LG → FPS Dispatch Trend")
        df2 = day_totals_lg.query("Day>=@day_range[0] & Day<=@day_range[1]")
        fig2 = px.line(df2, x="Day", y="Quantity_tons",
                       labels={"Quantity_tons":"Tons"}, markers=True)
        st.plotly_chart(fig2, use_container_width=True)

    # Vehicle & Stock
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Vehicle Utilization (LG→FPS)")
        vu = veh_usage.query("Day>=@day_range[0] & Day<=@day_range[1]")
        fig3 = px.area(vu, x="Day", y=["Trips_Used","Max_Trips"],
                       labels={"value":"Trips","variable":"Metric"})
        st.plotly_chart(fig3, use_container_width=True)
    with col4:
        st.subheader("LG Stock Levels")
        stock_slice = lg_stock.loc[day_range[0]:day_range[1], selected_lgs]
        fig4 = px.line(stock_slice, labels={"value":"Stock (t)","Day":"Day"})
        st.plotly_chart(fig4, use_container_width=True)

# ————————————————————————————————
# 5. Tab 2: FPS Report
# ————————————————————————————————
with tab2:
    st.subheader("FPS‐wise Dispatch Report")
    # Filter by slider range
    fps_df = dispatch_lg.query("Day>=@day_range[0] & Day<=@day_range[1]")
    # Aggregate per FPS
    report = (
        fps_df.groupby("FPS_ID")["Quantity_tons"]
        .sum()
        .reset_index()
        .merge(fps[["FPS_ID","FPS_Name"]], on="FPS_ID", how="left")
        .rename(columns={"Quantity_tons":"Total_Dispatched_tons"})
        .sort_values("Total_Dispatched_tons", ascending=False)
    )
    st.dataframe(report, use_container_width=True)

    # Download button
    def to_excel(df):
        buf = BytesIO()
        df.to_excel(buf, index=False)
        return buf.getvalue()

    excel_data = to_excel(report)
    st.download_button(
        label="📥 Download FPS Report",
        data=excel_data,
        file_name=f"fps_report_days_{day_range[0]}_to_{day_range[1]}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

dl_cg = to_excel(dispatch_cg)
dl_lg = to_excel(dispatch_lg)
st.download_button("Download CG→LG Dispatch", dl_cg, "cg_to_lg.xlsx")
st.download_button("Download LG→FPS Dispatch", dl_lg, "lg_to_fps.xlsx")
