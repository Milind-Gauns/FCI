import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# 1. Page config
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")

# 2. Export helper
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

# 4. Core metrics
DAYS      = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
DAILY_CAP = MAX_TRIPS * TRUCK_CAP

# Pre-dispatch offset
dt = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum()
cum = 0; adv = []
for d in range(1, DAYS+1):
    cum += dt.get(d, 0)
    over = (cum - DAILY_CAP * d) / DAILY_CAP
    adv.append(math.ceil(over) if over > 0 else 0)
X = max(adv); MIN_DAY = 1 - X; MAX_DAY = DAYS

# Aggregations
day_totals_cg = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum().reset_index().rename(columns={"Dispatch_Day":"Day"})
day_totals_lg = dispatch_lg.groupby("Day")["Quantity_tons"].sum().reset_index()
veh_usage     = dispatch_cg.groupby(["Day","LG_ID"])["Vehicle_ID"].nunique().reset_index(name="Trucks_Used")
lg_stock      = stock_levels[stock_levels["Entity Type"]=="LG"].pivot_table(index="Day", columns="Entity_ID", values="Stock_Level_tons", aggfunc="first").fillna(method="ffill")

# 5. Sidebar filters & quick KPIs
st.title("🚛 Grain Distribution Dashboard")
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Dispatch Window (days)", MIN_DAY, MAX_DAY, (MIN_DAY, MAX_DAY), format="%d")
    st.subheader("Select LGs")
    cols      = st.columns(4)
    lg_ids    = lgs["LG_ID"].astype(str).tolist()
    lg_names  = lgs["LG_Name"].tolist()
    selected_lgs = []
    for i, name in enumerate(lg_names):
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

# Main dispatch tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "CG→LG Overview", "LG→FPS Overview",
    "FPS Report", "FPS At-Risk",
    "FPS Data", "Downloads", "Metrics",
    "LG Insights"
])

# 6. CG→LG Overview
with tab1:
    df1 = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")
    fig1 = px.bar(df1, x="Day", y="Quantity_tons", text="Quantity_tons", title="CG→LG Dispatch")
    fig1.update_traces(texttemplate="%{text:.1f}t", textposition="outside")
    st.plotly_chart(fig1, use_container_width=True)

# 7. LG→FPS Overview
with tab2:
    df2 = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")
    fig2 = px.bar(df2, x="Day", y="Quantity_tons", text="Quantity_tons", title="LG→FPS Dispatch")
    fig2.update_traces(texttemplate="%{text:.1f}t", textposition="outside")
    st.plotly_chart(fig2, use_container_width=True)

# 8. FPS Report
with tab3:
    mask = (
        (dispatch_lg.Day >= 1) & (dispatch_lg.Day <= day_range[1]) &
        dispatch_lg.LG_ID.isin(selected_lgs)
    )
    fps_df = dispatch_lg[mask]
    report = (
        fps_df.groupby("FPS_ID")
        .agg(
            Total_Dispatched_tons=pd.NamedAgg("Quantity_tons","sum"),
            Trips_Count=pd.NamedAgg("Vehicle_ID","nunique"),
            Vehicle_IDs=pd.NamedAgg("Vehicle_ID", lambda vs: ",".join(map(str,sorted(set(vs)))))
        )
        .reset_index()
        .merge(fps[["FPS_ID","FPS_Name"]], on="FPS_ID", how="left")
        .sort_values("Total_Dispatched_tons", ascending=False)
    )
    st.dataframe(report, use_container_width=True)

# 9. FPS At-Risk
with tab4:
    arf = fps_stock.query("Day>=1 & Day<=@day_range[1] & At_Risk")
    st.dataframe(arf[["Day","FPS_ID","Stock_Level_tons","Reorder_Threshold_tons"]], use_container_width=True)
    st.download_button("Download At-Risk", to_excel(arf), "fps_at_risk.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# 10. FPS Data
with tab5:
    fps_data = []
    end_day = min(day_range[1], DAYS)
    for fid in report["FPS_ID"]:
        s = fps_stock[(fps_stock.FPS_ID==fid)&(fps_stock.Day==end_day)]["Stock_Level_tons"]
        stock_now = float(s.iloc[0]) if not s.empty else 0.0
        fut = dispatch_lg[(dispatch_lg.FPS_ID==fid)&(dispatch_lg.Day> end_day)]["Day"]
        nd = int(fut.min()) if not fut.empty else None
        days_to = nd-end_day if nd else None
        fps_data.append({
            "FPS_ID": fid,
            "Current_Stock_tons": stock_now,
            "Next_Receipt_Day": nd,
            "Days_To_Receipt": days_to
        })
    df5 = pd.DataFrame(fps_data)
    st.dataframe(df5, use_container_width=True)
    st.download_button("Download FPS Data", to_excel(df5), "fps_data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# 11. Downloads
with tab6:
    st.download_button("Download FPS Report (Excel)", to_excel(report), "FPS_Report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    pdf_buf = BytesIO()
    with PdfPages(pdf_buf) as pdf:
        fig, ax = plt.subplots(figsize=(8, len(report)*0.3 + 1))
        ax.axis('off')
        tbl = ax.table(cellText=report.values, colLabels=report.columns, loc='center')
        tbl.auto_set_font_size(False); tbl.set_fontsize(10)
        pdf.savefig(fig, bbox_inches='tight')
    st.download_button("Download FPS Report (PDF)", pdf_buf.getvalue(), "FPS_Report.pdf", "application/pdf")

# 12. Metrics
with tab7:
    sel_days = day_range[1] - max(day_range[0],1) + 1
    avg_cg = cg_sel/sel_days if sel_days>0 else 0
    avg_lg = lg_sel/sel_days if sel_days>0 else 0
    avg_tr = veh_usage.query("Day>=1 & Day<=@day_range[1]")["Trips_Used"].mean()
    pct_f = (avg_tr/MAX_TRIPS)*100 if MAX_TRIPS else 0
    lg_on = lg_stock.loc[end_day, selected_lgs].sum()
    fps_on = fps_stock.query(f"Day==@end_day")["Stock_Level_tons"].sum()
    lg_cap = lgs[lgs.LG_ID.isin(map(str,selected_lgs))]["Storage_Capacity_tons"].sum()
    pct_lg = (lg_on/lg_cap)*100 if lg_cap else 0
    fps_zero = fps_stock.query(f"Day=={end_day} & Stock_Level_tons==0")["FPS_ID"].nunique()
    fps_r    = fps_stock.query(f"Day=={end_day} & At_Risk")["FPS_ID"].nunique()
    disp     = day_totals_lg.query(f"Day<={end_day}")["Quantity_tons"].sum()
    pct_p    = (disp/total_plan)*100 if total_plan else 0
    rem      = total_plan-disp; days_r = math.ceil(rem/DAILY_CAP) if DAILY_CAP else None

    KP = [
        ("Total CG→LG (t)", f"{cg_sel:,.1f}"),
        ("Total LG→FPS (t)", f"{lg_sel:,.1f}"),
        ("Avg CG→LG (t/d)", f"{avg_cg:,.1f}"),
        ("Avg LG→FPS (t/d)", f"{avg_lg:,.1f}"),
        ("Avg Trips/Day", f"{avg_tr:.1f}"),
        ("% Fleet Util", f"{pct_f:.1f}%"),
        ("LG Stock (t)", f"{lg_on:,.1f}"),
        ("FPS Stock (t)", f"{fps_on:,.1f}"),
        ("% LG Cap Fill", f"{pct_lg:.1f}%"),
        ("FPS Stock-Outs", f"{fps_zero}"),
        ("FPS At-Risk Count", f"{fps_r}"),
        ("% Plan Completed", f"{pct_p:.1f}%"),
        ("Days Remaining", f"{days_r}")
    ]
    cols = st.columns(3)
    for i, (label, val) in enumerate(KP):
        cols[i%3].metric(label, val)

# 13. LG Insights
with tab8:
    st.subheader("LG Insights")
    insights = []
    for lg in selected_lgs:
        # Daily CG→LG received
        mask = (dispatch_cg.LG_ID == lg) & (dispatch_cg.Dispatch_Day >= day_range[0]) & (dispatch_cg.Dispatch_Day <= day_range[1])
        daily_received = dispatch_cg.loc[mask, "Quantity_tons"].sum()
        # Cumulative = same over window
        cum_received = daily_received
        avg_per_day = daily_received / (day_range[1]-max(day_range[0],1)+1)
        # Current stock
        stock_now = lg_stock.loc[end_day, lg] if lg in lg_stock.columns else 0
        # Next arrival
        future = dispatch_cg[(dispatch_cg.LG_ID==lg) & (dispatch_cg.Dispatch_Day > end_day)]["Dispatch_Day"]
        next_arr = int(future.min()) if not future.empty else None
        days_to  = next_arr - end_day if next_arr else None
        # Incoming scheduled
        incoming = dispatch_cg[(dispatch_cg.LG_ID==lg) & (dispatch_cg.Dispatch_Day > end_day)]["Quantity_tons"].sum()
        # Trucks used per day avg
        tu = veh_usage[veh_usage.LG_ID==lg]["Trucks_Used"] if "LG_ID" in veh_usage.columns else pd.Series()
        avg_trucks = tu.mean() if not tu.empty else 0

        insights.append({
            "LG_ID": lg,
            "LG_Name": lgs.set_index("LG_ID").loc[str(lg), "LG_Name"],
            "Daily_Received_tons": daily_received,
            "Cumulative_Received_tons": cum_received,
            "Avg_per_day_tons": avg_per_day,
            "Current_Stock_tons": stock_now,
            "Next_Arrival_Day": next_arr,
            "Days_To_Next_Arrival": days_to,
            "Incoming_Scheduled_tons": incoming,
            "Avg_Trucks_Per_Day": avg_trucks
        })
    df_ins = pd.DataFrame(insights)
    st.dataframe(df_ins, use_container_width=True)
    st.download_button("Download LG Insights", to_excel(df_ins), "lg_insights.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
