import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# 1. Page config (first)
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

settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data("distribution_dashboard_output.xlsx")

# 4. Core metrics
DAYS      = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
DAILY_CAP = MAX_TRIPS * TRUCK_CAP

# Pre‐dispatch offset
dt = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum()
cum = 0; adv = []
for d in range(1, DAYS+1):
    cum += dt.get(d,0)
    over = (cum - DAILY_CAP*d)/DAILY_CAP
    adv.append(math.ceil(over) if over>0 else 0)
X = max(adv); MIN_DAY = 1-X; MAX_DAY = DAYS

# Summaries
day_totals_cg = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum().reset_index().rename(columns={"Dispatch_Day":"Day"})
day_totals_lg = dispatch_lg.groupby("Day")["Quantity_tons"].sum().reset_index()
veh_usage     = dispatch_lg.groupby("Day")["Vehicle_ID"].nunique().reset_index(name="Trips_Used")
veh_usage["Max_Trips"] = MAX_TRIPS
lg_stock      = stock_levels[stock_levels["Entity Type"]=="LG"].pivot_table(index="Day",columns="Entity_ID",values="Stock_Level_tons",aggfunc="first").fillna(method="ffill")

# FPS stock & at-risk
fps_stock = stock_levels[stock_levels["Entity Type"]=="FPS"].rename(columns={"Entity_ID":"FPS_ID"})
fps_stock = fps_stock.merge(fps[["FPS_ID","Reorder_Threshold_tons"]],on="FPS_ID",how="left")
fps_stock["At_Risk"] = fps_stock["Stock_Level_tons"] <= fps_stock["Reorder_Threshold_tons"]

total_plan = day_totals_lg.Quantity_tons.sum()

# 5. Sidebar filters & KPIs
st.title("🚛 Grain Distribution Dashboard")
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Dispatch Window (days)", MIN_DAY, MAX_DAY, (MIN_DAY,MAX_DAY), format="%d")
    st.subheader("Select LGs")
    cols = st.columns(4)
    lg_ids   = lgs["LG_ID"].astype(str).tolist()
    lg_names = lgs["LG_Name"].tolist()
    selected_lgs = []
    for i,name in enumerate(lg_names):
        if cols[i%4].checkbox(name,True,key=f"lg_{i}"):
            selected_lgs.append(int(lg_ids[i]))
    st.markdown("---")
    cg_sel = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    lg_sel = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")["Quantity_tons"].sum()
    st.header("Quick KPIs")
    st.metric("CG→LG Total (t)", f"{cg_sel:,.1f}")
    st.metric("LG→FPS Total (t)", f"{lg_sel:,.1f}")
    st.metric("Max Trucks/Day", f"{MAX_TRIPS}")
    st.metric("Truck Capacity (t)", f"{TRUCK_CAP}")

# 6. CG→LG Overview
st.subheader("CG → LG Dispatch")
df1 = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")
fig1=px.bar(df1,x="Day",y="Quantity_tons",text="Quantity_tons")
fig1.update_traces(texttemplate="%{text:.1f}t",textposition="outside")
st.plotly_chart(fig1,use_container_width=True)

# 7. LG→FPS Overview
st.subheader("LG → FPS Dispatch")
df2 = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")
fig2=px.bar(df2,x="Day",y="Quantity_tons",text="Quantity_tons")
fig2.update_traces(texttemplate="%{text:.1f}t",textposition="outside")
st.plotly_chart(fig2,use_container_width=True)

# 8. FPS Report (mask instead of query dynamic)
st.subheader("FPS-wise Dispatch Details")
mask = (
    (dispatch_lg.Day >= 1) &
    (dispatch_lg.Day <= day_range[1]) &
    dispatch_lg.LG_ID.isin(selected_lgs)
)
fps_df = dispatch_lg[mask]
report = (
    fps_df.groupby("FPS_ID")
    .agg(
        Total_Dispatched_tons=pd.NamedAgg("Quantity_tons","sum"),
        Trips_Count=pd.NamedAgg("Vehicle_ID","nunique"),
        Vehicle_IDs=pd.NamedAgg("Vehicle_ID",lambda vs: ",".join(map(str,sorted(set(vs)))))
    )
    .reset_index()
    .merge(fps[["FPS_ID","FPS_Name"]],on="FPS_ID",how="left")
    .sort_values("Total_Dispatched_tons",ascending=False)
)
st.dataframe(report,use_container_width=True)

# 9. FPS At-Risk
st.subheader("FPS At-Risk List")
mask2 = (
    (fps_stock.Day >= 1) &
    (fps_stock.Day <= day_range[1]) &
    (fps_stock.FPS_ID.isin(report.FPS_ID)) &
    fps_stock.At_Risk
)
arf = fps_stock[mask2]
st.dataframe(arf[["Day","FPS_ID","Stock_Level_tons","Reorder_Threshold_tons"]],use_container_width=True)
st.download_button("Download At-Risk",to_excel(arf),"fps_at_risk.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# 10. FPS Data
st.subheader("FPS Stock & Upcoming Receipts")
end_day = min(day_range[1],DAYS)
fps_data=[]
for fid in report["FPS_ID"]:
    s = fps_stock[(fps_stock.FPS_ID==fid)&(fps_stock.Day==end_day)]["Stock_Level_tons"]
    stock_now=float(s.iloc[0]) if not s.empty else 0.0
    fut = dispatch_lg[(dispatch_lg.FPS_ID==fid)&(dispatch_lg.Day> end_day)]["Day"]
    nd = int(fut.min()) if not fut.empty else None
    dt = nd-end_day if nd else None
    fps_data.append({"FPS_ID":fid,"Current_Stock_tons":stock_now,"Next_Receipt_Day":nd,"Days_To_Receipt":dt})
fps_data_df=pd.DataFrame(fps_data)
st.dataframe(fps_data_df,use_container_width=True)
st.download_button("Download FPS Data",to_excel(fps_data_df),"fps_data.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# 11. Downloads
st.subheader("Download FPS Report")
st.download_button("Download Excel",to_excel(report),"FPS_Report.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
pdf_buf=BytesIO()
with PdfPages(pdf_buf) as pdf:
    fig,ax=plt.subplots(figsize=(8,len(report)*0.3+1));ax.axis('off')
    tbl=ax.table(cellText=report.values,colLabels=report.columns,loc='center');tbl.auto_set_font_size(False);tbl.set_fontsize(10)
    pdf.savefig(fig,bbox_inches='tight')
st.download_button("Download PDF",pdf_buf.getvalue(),"FPS_Report.pdf","application/pdf")

# 12. Metrics
st.subheader("Key Performance Indicators")
sel_days = day_range[1]-max(day_range[0],1)+1
avg_cg = cg_sel/sel_days if sel_days>0 else 0
avg_lg = lg_sel/sel_days if sel_days>0 else 0
avg_tr = veh_usage.query(f"Day>=1 & Day<=@day_range[1]")["Trips_Used"].mean()
pct_f = (avg_tr/MAX_TRIPS)*100 if MAX_TRIPS else 0
lg_on = lg_stock.loc[end_day, selected_lgs].sum()
fps_on = fps_stock[fps_stock.Day==end_day]["Stock_Level_tons"].sum()
lg_cap = lgs[lgs.LG_ID.astype(str).isin(map(str,selected_lgs))]["Storage_Capacity_tons"].sum()
pct_lg=(lg_on/lg_cap)*100 if lg_cap else 0
fps_zero=fps_stock[(fps_stock.Day==end_day)&(fps_stock.Stock_Level_tons==0)]["FPS_ID"].nunique()
fps_r  = fps_stock[(fps_stock.Day==end_day)&(fps_stock.At_Risk)]["FPS_ID"].nunique()
disp   = day_totals_lg.query(f"Day<={end_day}")["Quantity_tons"].sum()
pct_p  = (disp/total_plan)*100 if total_plan else 0
rem    = total_plan-disp; days_r=math.ceil(rem/DAILY_CAP) if DAILY_CAP else None

KP = [
    ("Total CG→LG (t)",f"{cg_sel:,.1f}"),
    ("Total LG→FPS (t)",f"{lg_sel:,.1f}"),
    ("Avg CG→LG (t/d)",f"{avg_cg:,.1f}"),
    ("Avg LG→FPS (t/d)",f"{avg_lg:,.1f}"),
    ("Avg Trips/Day",f"{avg_tr:.1f}"),
    ("% Fleet Util",f"{pct_f:.1f}%"),
    ("LG Stock (t)",f"{lg_on:,.1f}"),
    ("FPS Stock (t)",f"{fps_on:,.1f}"),
    ("% LG Cap Fill",f"{pct_lg:.1f}%"),
    ("FPS Stock-Outs",f"{fps_zero}"),
    ("FPS At-Risk",f"{fps_r}"),
    ("% Plan Completed",f"{pct_p:.1f}%"),
    ("Days Remaining",f"{days_r}")
]
cols=st.columns(3)
for i,(l,v) in enumerate(KP): cols[i%3].metric(l,v)
