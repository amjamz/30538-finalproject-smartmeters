import pandas as pd
import geopandas as gpd
import altair as alt
import json
from shapely.geometry import Point
from shiny import App, render, ui, reactive
from shinywidgets import output_widget, render_altair
from datetime import datetime

sg_path = "C:/Users/RedthinkerDantler/Documents/GitHub/DPPP2/30538-finalproject-smartmeters/"
current_path = sg_path

substations_UKPN = pd.read_csv(current_path + 'data/substations_UKPN.csv')

substations_UKPN['timestamp'] = pd.to_datetime(substations_UKPN['timestamp'])
substations_UKPN['date'] = substations_UKPN['timestamp'].dt.date
substations_UKPN['day_of_week'] = substations_UKPN['timestamp'].dt.day_name()
substations_UKPN['time_of_day'] = substations_UKPN['timestamp'].dt.time

# Set up GeoDataFrame
substations_UKPN['geometry'] = substations_UKPN.apply(lambda row: Point(row['longitude'], row['latitude']), axis=1)
substations_UKPN_gdf = gpd.GeoDataFrame(substations_UKPN, geometry='geometry')
substations_UKPN_gdf = substations_UKPN_gdf.set_crs("EPSG:4326", inplace=True)

# Load Bedford/Cambridge boundary data
epn_boundaries = gpd.read_file(current_path + 'data/ukpn-epn-area-operational-boundaries/ukpn-epn-area-operational-boundaries.shp')
bedford_cambridge = epn_boundaries[epn_boundaries['ops_area'] == 'Bedford/Cambridge']

# Spatial join to filter substations within Bedford/Cambridge region
bedford_cambridge_substations = gpd.sjoin(
    substations_UKPN_gdf,  # Substation GeoDataFrame
    bedford_cambridge,     # Bedford/Cambridge region GeoDataFrame
    how='inner',
    predicate='within'
)

# Clean substation column
bedford_cambridge_substations['substation'] = bedford_cambridge_substations['substation'].apply(lambda s: s[9:])

# Load substation boundary data
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

# Merge on substation and site_functional_location columns
bedford_cambridge_substations = epn_substation_boundaries.merge(
    bedford_cambridge_substations, 
    left_on="site_functional_location", 
    right_on="substation", 
    how="inner", 
    suffixes=('_boundaries', '_substations')
)

bedford_cambridge_substations_gdf = gpd.GeoDataFrame(bedford_cambridge_substations, geometry='geometry_boundaries')

# Time related options slider
time_options = (
    bedford_cambridge_substations_gdf[["date", "time_of_day"]]
    .drop_duplicates()
    .sort_values(["date", "time_of_day"])
)

time_options["time_label"] = time_options["date"].astype(str) + " " + time_options["time_of_day"].astype(str)
time_labels = time_options["time_label"].tolist()

# convert Gdf to geojson
def geojson_from_gdf(gdf):
    """
    Convert a GeoDataFrame to GeoJSON format. Ensures that Point geometries are serialized correctly.
    """
    # correct CRS
    gdf = gdf.to_crs(epsg=4326) 
    
    # if the geometry exists
    if 'geometry_boundaries' not in gdf.columns:
        print("Error: Geometry column 'geometry_boundaries' not found.")
        return {}

    # serialize geometries (Point geometries for geojson
    gdf['geometry'] = gdf['geometry_boundaries'].apply(lambda geom: {'type': 'Point', 'coordinates': [geom.centroid.x, geom.centroid.y]})
    geojson_data = json.loads(gdf.to_json())  # Convert to GeoJSON format
    return geojson_data

# UI
app_ui = ui.page_fluid(
    ui.h2("Smart Meter Energy Consumption: Bedford/Cambridge Region"),
    ui.input_slider(
        "time_slider",
        "Select Time (Date and Time of Day)",
        min=0,
        max=len(time_labels) - 1,
        value=0,
        step=1,
        ticks=False,
        animate=True,
        width="100%",
    ),
    ui.tags.div(ui.output_text("current_time"), style="font-size:16px; font-weight: bold;"),
    output_widget("consumption_map", height="600px"),
)

def server(input, output, session):
    @reactive.Calc
    def filtered_data():
        selected_time = time_labels[input.time_slider()]
        selected_date, selected_time_of_day = selected_time.split(" ")

        print(f"Selected Date: {selected_date}, Selected Time of Day: {selected_time_of_day}")

        # ensure date is in datetime forma
        bedford_cambridge_substations_gdf['date'] = pd.to_datetime(bedford_cambridge_substations_gdf['date']).dt.date

        # convert the selected_time_of_day to datetime.time format
        selected_time_of_day = datetime.strptime(selected_time_of_day, "%H:%M:%S").time()

        # check if the filtering will work
        print(f"Unique Dates in DataFrame: {bedford_cambridge_substations_gdf['date'].unique()}")
        print(f"Unique Time of Day in DataFrame: {bedford_cambridge_substations_gdf['time_of_day'].unique()}")

        # Filter : selected date and time
        filtered_df = bedford_cambridge_substations_gdf[
            (bedford_cambridge_substations_gdf["date"] == pd.to_datetime(selected_date).date())  # Match date format
            & (bedford_cambridge_substations_gdf["time_of_day"] == selected_time_of_day)  # Match time format
        ]
        
        # Check if filtered data is empty
        if filtered_df.empty:
            print(f"No data available for {selected_date} {selected_time_of_day}")
        else:
            print(f"Filtered Data (first 5 rows): \n{filtered_df.head()}")

        # ensure filtered DataFrame still has the geometry column and is a valid GeoDataFrame
        if filtered_df.empty:
            return filtered_df
        
        filtered_df = filtered_df.copy()  
        filtered_df = filtered_df.set_geometry('geometry_boundaries') 
        
        # the average consumption for the selected time
        avg_consumption = filtered_df['consumption'].mean()
        
        # update ui with the average consumption value 
        output.current_time = f"Selected Time: {selected_date} {selected_time_of_day} | Average Consumption: {avg_consumption:.2f} kWh"
        
        return filtered_df

    @output
    @render_altair
    def consumption_map():
        filtered_df = filtered_data() 
        
        # If filtered data is empty, skip rendering
        if filtered_df.empty:
            return alt.Chart().mark_text().encode(
                text=alt.value('No data available for this time')
            )

        #from filtered gdf
        geojson_data = geojson_from_gdf(filtered_df)

        # ensure GeoJSON is not empty
        if not geojson_data:
            return alt.Chart().mark_text().encode(
                text=alt.value('Error in GeoJSON generation')
            )

        chart = alt.Chart(geojson_data).mark_geoshape().encode(
            color='consumption:Q',  # Map consumption to color
            tooltip=['substation:N', 'consumption:Q', 'date:T', 'time_of_day:T']
        ).properties(
            width=600,
            height=400
        )

        return chart

app = App(app_ui, server)
