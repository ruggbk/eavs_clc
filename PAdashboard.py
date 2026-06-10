import json
from urllib.request import urlopen

import plotly.express as px
import streamlit as st
import pandas as pd

from eavs.config import CLEANED_DATA_DIR, RAW_DATA_DIR

st.set_page_config(page_title="Pennsylvania Voter Participation (2024)", layout="wide")

PHILLY_REGION = ["PHILADELPHIA COUNTY", "MONTGOMERY COUNTY", "BUCKS COUNTY", "DELAWARE COUNTY", "CHESTER COUNTY"]

DEMO_COLS = [
    "White Alone",
    "Black or African American Alone",
    "Hispanic or Latino",
    "Asian Alone",
]

MAP_METRICS = {
    "Registration Rate (% of CVAP)": "registration_rate",
    "Mail Ballot Rejection Rate (%)": "mail_rejection_rate",
    "Provisional Ballot Rejection Rate (%)": "provisional_rejection_rate",
    "Voter Removals per 1,000 Registered": "removal_rate",
    "CVAP Share: White Alone (%)": "share_white",
    "CVAP Share: Black or African American (%)": "share_black",
    "CVAP Share: Hispanic or Latino (%)": "share_hispanic",
    "CVAP Share: Asian Alone (%)": "share_asian",
}


@st.cache_data
def load_data() -> pd.DataFrame:
    eavs_pa = pd.read_parquet(
        CLEANED_DATA_DIR / "2024_cleaned.parquet",
        filters=[("state_abbr", "==", "PA")],
    )
    cvap_2024 = pd.read_csv(
        RAW_DATA_DIR / "cvap" / "CVAP_2020-2024_ACS_csv_files" / "County.csv"
    )
    cvap_PA = cvap_2024[cvap_2024["geoname"].str.contains("Pennsylvania")]
    cvap_pivot = (
        cvap_PA.pivot_table(index=["geoid", "geoname"], columns="lntitle", values="cvap_est")
        .reset_index()
    )
    cvap_pivot.columns.name = None
    cvap_pivot["geoid"] = cvap_pivot["geoid"].str.replace("0500000US", "")

    merged = (
        eavs_pa
        .merge(cvap_pivot, left_on="fips_code", right_on="geoid", how="left")
        .drop(columns="geoid")
    )
    for col in merged.select_dtypes(exclude="number").columns:
        converted = pd.to_numeric(merged[col], errors="coerce")
        if converted.notna().any():
            merged[col] = converted
    return merged


@st.cache_data
def load_counties_geojson() -> dict:
    url = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
    with urlopen(url) as response:
        return json.load(response)


df = load_data()
counties_geojson = load_counties_geojson()

# Precompute map metrics on full PA dataset
map_df = df.copy()
map_df["registration_rate"] = (map_df["registered_eligible_voters"] / map_df["Total"] * 100).round(1)
map_df["mail_rejection_rate"] = (
    map_df["mail_ballots_rejected_total"] /
    (map_df["mail_ballots_counted"] + map_df["mail_ballots_rejected_total"]) * 100
).round(1)
map_df["provisional_rejection_rate"] = (
    map_df["provisional_ballots_rejected_total"] / map_df["provisional_ballots_cast_total"] * 100
).round(1)
map_df["removal_rate"] = (
    map_df["voters_removed_total_2020_2022"] / map_df["registered_eligible_voters"] * 1000
).round(1)
map_df["share_white"] = (map_df["White Alone"] / map_df["Total"] * 100).round(1)
map_df["share_black"] = (map_df["Black or African American Alone"] / map_df["Total"] * 100).round(1)
map_df["share_hispanic"] = (map_df["Hispanic or Latino"] / map_df["Total"] * 100).round(1)
map_df["share_asian"] = (map_df["Asian Alone"] / map_df["Total"] * 100).round(1)

# Sidebar
st.sidebar.title("Filters")
region_filter = st.sidebar.radio("Region", ["Philly Region", "All PA"])
counties = sorted(
    df[df["jurisdiction_name"].isin(PHILLY_REGION)]["jurisdiction_name"].unique()
    if region_filter == "Philly Region"
    else df["jurisdiction_name"].unique()
)
selected = st.sidebar.multiselect("Counties", counties, default=counties)
filtered = df[df["jurisdiction_name"].isin(selected)]


st.title("Pennsylvania Voter Participation (2024)")

# --- County Map ---
st.header("County Map")
metric_label = st.selectbox("Metric", list(MAP_METRICS.keys()))
metric_col = MAP_METRICS[metric_label]

fig = px.choropleth(
    map_df,
    geojson=counties_geojson,
    locations="fips_code",
    color=metric_col,
    color_continuous_scale="Blues",
    scope="usa",
    hover_name="jurisdiction_name",
    hover_data={metric_col: True, "fips_code": False},
    labels={metric_col: metric_label},
)
fig.update_geos(fitbounds="locations", visible=False)
fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=500)
st.plotly_chart(fig, use_container_width=True)

# --- Registration Access ---
st.header("Registration Access")

total_cvap = filtered["Total"].sum()
total_registered = filtered["registered_eligible_voters"].sum()

c1, c2 = st.columns(2)
c1.metric("CVAP (Eligible Citizens)", f"{total_cvap:,.0f}")
c2.metric("Registered Voters", f"{total_registered:,.0f}", f"{total_registered / total_cvap:.1%} of CVAP" if total_cvap else "N/A")

st.subheader("New Registrations by Channel")
st.caption(
    "DMV and advocacy group data not reported by Pennsylvania in 2024. "
    "Armed forces registrations are likely undercounted due to known reporting gaps in the chain of custody."
)
channel_df = pd.DataFrame({
    "Channel": ["Online", "In Person", "Mail / Fax / Email", "Disability Agency", "Armed Forces"],
    "New Registrations": [
        filtered["new_registrations_online"].sum(),
        filtered["new_registrations_in_person"].sum(),
        filtered["new_registrations_mail_fax_email"].sum(),
        filtered["new_registrations_disability_agency"].sum(),
        filtered["new_registrations_armed_forces"].sum(),
    ],
})
st.bar_chart(channel_df, x="Channel", y="New Registrations")

# --- Voter Roll Health ---
st.header("Voter Roll Health")

c1, c2, c3 = st.columns(3)
c1.metric("Active Voters", f"{filtered['active_voters'].sum():,.0f}")
c2.metric("Inactive Voters", f"{filtered['inactive_voters'].sum():,.0f}")
c3.metric("Voters Removed (2020–2022)", f"{filtered['voters_removed_total_2020_2022'].sum():,.0f}")

# --- Ballot Access ---
st.header("Ballot Access")

mail_rejected = filtered["mail_ballots_rejected_total"].sum()
mail_counted = filtered["mail_ballots_counted"].sum()
prov_rejected = filtered["provisional_ballots_rejected_total"].sum()
prov_cast = filtered["provisional_ballots_cast_total"].sum()

c1, c2, c3 = st.columns(3)
c1.metric(
    "Mail Ballot Rejection Rate",
    f"{mail_rejected / (mail_counted + mail_rejected):.1%}" if (mail_counted + mail_rejected) else "N/A",
)
c2.metric(
    "Provisional Ballot Rejection Rate",
    f"{prov_rejected / prov_cast:.1%}" if prov_cast else "N/A",
)
c3.metric("Total Drop Boxes", f"{filtered['drop_boxes_total'].sum():,.0f}")

st.subheader("Mail Ballot Rejection Reasons")
mail_rejection_df = pd.DataFrame({
    "Reason": ["Late", "Missing Voter Signature", "Non-matching Signature", "No Secrecy Envelope", "Missing Documentation", "Voter Not Eligible"],
    "Rejected Ballots": [
        filtered["mail_ballots_rejected_late"].sum(),
        filtered["mail_ballots_rejected_missing_voter_signature"].sum(),
        filtered["mail_ballots_rejected_non_matching_voter_signature"].sum(),
        filtered["mail_ballots_rejected_no_secrecy_envelope"].sum(),
        filtered["mail_ballots_rejected_missing_documentation"].sum(),
        filtered["mail_ballots_rejected_voter_not_eligible"].sum(),
    ],
})
st.bar_chart(mail_rejection_df, x="Reason", y="Rejected Ballots")

# --- Demographics ---
st.header("CVAP Demographics by County")
available = [c for c in DEMO_COLS if c in filtered.columns]
demo_df = filtered[["jurisdiction_name"] + available].set_index("jurisdiction_name")
st.bar_chart(demo_df)
