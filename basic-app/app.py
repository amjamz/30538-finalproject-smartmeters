import pandas as pd
import geopandas as gpd
import json
from shapely.geometry import Point
from shiny import App, render, ui, reactive
from datetime import datetime
import matplotlib.pyplot as plt
import contextily as cx
from matplotlib.figure import Figure

# Paths
sg_path = "C:/Users/RedthinkerDantler/Documents/GitHub/DPPP2/30538-finalproject-smartmeters/"
current_path = sg_path

# Load and preprocess data
substations_UKPN = pd.read_csv(current_path + 'data/substations_UKPN.csv')
substations_UKPN['timestamp'] = pd.to_datetime(substations_UKPN['timestamp'])
substations_UKPN['date'] = substations_UKPN['timestamp'].dt.date
substations_UKPN['day_of_week'] = substations_UKPN['timestamp'].dt.day_name()
substations_UKPN['time_of_day'] = substations_UKPN['timestamp'].dt.time
substations_UKPN['geometry'] = substations_UKPN.apply(lambda row: Point(row['longitude'], row['latitude']), axis=1)

# Create GeoDataFrame
substations_UKPN_gdf = gpd.GeoDataFrame(substations_UKPN, geometry='geometry')
substations_UKPN_gdf.set_crs("EPSG:4326", inplace=True)

# Load boundary data
epn_boundaries = gpd.read_file(current_path + 'data/ukpn-epn-area-operational-boundaries/ukpn-epn-area-operational-boundaries.shp')
bedford_cambridge = epn_boundaries[epn_boundaries['ops_area'] == 'Bedford/Cambridge']

# Spatial join
bedford_cambridge_substations = gpd.sjoin(
    substations_UKPN_gdf,
    bedford_cambridge,
    how='inner',
    predicate='within'
)

bedford_cambridge_substations['substation'] = bedford_cambridge_substations['substation'].apply(lambda s: s[9:])
epn_substation_boundaries = gpd.read_file(current_path + "data/ukpn_secondary_postcode_area/ukpn_secondary_postcode_area.shp").rename(columns={
    "dno": "DNO",
    "sitefunctio": "site_functional_location",
    "demand_head": "demand_headroom",
    "onanrating": "ONAN_rating",
    "source": "source",
    "utilisation": "utilisation_band",
    "predicted_y": "predicted_year_of_reinforcement",
    "customer_co": "customer_count"
})

bedford_cambridge_substations = epn_substation_boundaries.merge(
    bedford_cambridge_substations,
    left_on="site_functional_location",
    right_on="substation",
    how="inner",
    suffixes=('_boundaries', '_substations')
)

bedford_cambridge_substations_gdf = gpd.GeoDataFrame(bedford_cambridge_substations, geometry='geometry_boundaries')

# Time slider options
time_options = (
    bedford_cambridge_substations_gdf[["date", "time_of_day"]]
    .drop_duplicates()
    .sort_values(["date", "time_of_day"])
)
time_options["time_label"] = time_options["date"].astype(str) + " " + time_options["time_of_day"].astype(str)
time_labels = time_options["time_label"].tolist()

# UI
app_ui = ui.page_fluid(
    ui.h2("Smart Meter Energy Consumption: Bedford/Cambridge Region"),
    ui.input_slider(
        "time_slider",
        "Half Hour Intervals from 00:30 to 24:00",
        min=0,
        max=len(time_labels) - 1,
        value=0,
        step=1,
        ticks=False,
        animate=True,
        width="100%",
    ),
    ui.tags.div(ui.output_text("current_time"), style="font-size:16px; font-weight: bold;"),
    ui.output_plot("consumption_map"),
)

def server(input, output, session):
    @reactive.Calc
    def filtered_data():
        selected_time = time_labels[input.time_slider()]
        selected_date, selected_time_of_day = selected_time.split(" ")

        # Filter data by date and time
        filtered_df = bedford_cambridge_substations_gdf[(
            bedford_cambridge_substations_gdf["date"] == pd.to_datetime(selected_date).date()) &
            (bedford_cambridge_substations_gdf["time_of_day"] == datetime.strptime(selected_time_of_day, "%H:%M:%S").time())
        ]

        # Convert datetime to string for JSON serialization
        filtered_df["date"] = filtered_df["date"].astype(str)
        filtered_df["time_of_day"] = filtered_df["time_of_day"].astype(str)
        return filtered_df

    @output
    @render.ui
    def current_time():
        selected_time = time_labels[input.time_slider()]
        selected_date, selected_time_of_day = selected_time.split(" ")

        filtered_df = filtered_data()
        if filtered_df.empty:
            return f"Selected Time: {selected_date} {selected_time_of_day} | No data available."

        avg_consumption = filtered_df['consumption'].mean()
        return f"Selected Time: {selected_date} {selected_time_of_day} | Avg Consumption: {avg_consumption:.2f} kWh"

    @output
    @render.plot
    def consumption_map():
        filtered_df = filtered_data()

        # Handle empty filtered data
        if filtered_df.empty:
            fig = plt.figure(figsize=(6, 6))
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=14)
            return fig

        # Ensure CRS alignment
        if not bedford_cambridge.crs.equals(filtered_df.crs):
            filtered_df = filtered_df.to_crs(bedford_cambridge.crs)

        # Create plot
        fig, ax = plt.subplots(figsize=(12, 10))

        # Plot boundaries
        bedford_cambridge.boundary.plot(ax=ax, color="blue", linewidth=0.5, label="Boundaries")

        # Plot substations with consumption data
        filtered_df.plot(
            ax=ax,
            marker="o",
            markersize=3,
            column="consumption",
            cmap="coolwarm",
            legend=True,
            legend_kwds={"label": "Consumption (kWh)"},
        )

        # Add basemap
        cx.add_basemap(
            ax,
            crs=bedford_cambridge.crs.to_string(),
            source=cx.providers.CartoDB.Voyager,
            attribution=False,
        )

        # Add average consumption annotation
        avg_consumption = filtered_df["consumption"].mean()
        ax.annotate(
            f"Avg Consumption: {avg_consumption:.2f} kWh",
            xy=(0.5, 0.95),
            xycoords="axes fraction",
            fontsize=12,
            ha="center",
            color="darkred",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="darkred"),
        )

        # Set title with current time
        selected_time = time_labels[input.time_slider()]
        ax.set_title(f"Energy Consumption on {selected_time}", fontsize=14)

        # Set the zoom region based on the substation locations
        lat_min, lat_max = filtered_df['geometry_substations'].y.min(), filtered_df['geometry_substations'].y.max()
        lon_min, lon_max = filtered_df['geometry_substations'].x.min(), filtered_df['geometry_substations'].x.max()
        ax.set_xlim(lon_min - 0.01, lon_max + 0.01)  # Adjust bounds to zoom in
        ax.set_ylim(lat_min - 0.01, lat_max + 0.01)

        ax.set_xlabel("Longitude", fontsize=12)
        ax.set_ylabel("Latitude", fontsize=12)

        plt.subplots_adjust(left=0.4)  # move plot left

        ax.set_aspect('equal', 'box')

        return fig

app = App(app_ui, server)
