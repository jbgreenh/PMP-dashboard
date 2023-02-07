import streamlit as st
import pandas as pd
import altair as alt
from vega_datasets import data
from datetime import datetime
from shillelagh.backends.apsw.db import connect

st.set_page_config(layout="wide")
alt.data_transformers.disable_max_rows()

ALL_AZ_COUNTIES = [ # sorted descending by population
    'Maricopa', 
    'Pima', 
    'Pinal', 
    'Yavapai', 
    'Mohave', 
    'Yuma', 
    'Coconino', 
    'Cochise', 
    'Navajo', 
    'Apache', 
    'Gila', 
    'Santa Cruz', 
    'Graham', 
    'La Paz', 
    'Greenlee'
    ]

X_DATE = '2022-01-17' # actually 2023

county_codes = pd.read_csv('data/county_codes.csv', index_col=None)

conn = connect(':memory:')

@st.cache(ttl=600)
def run_query(query):
    result = conn.execute(query)
    res_df = pd.DataFrame(result.fetchall())
    res_df.columns = [i[0] for i in result.description]
    return res_df

@st.cache
def convert_df(df):
    return df.to_csv(index=False).encode('utf-8')

sheet_url = st.secrets['public_gsheets_url']
result = run_query(f'SELECT * FROM "{sheet_url}"')

bp = result.copy()
bp['Prescription Count'].fillna(0, inplace=True)
bp['Month, Year of Filled At'] = pd.to_datetime(bp['Month, Year of Filled At']).dt.date

start_date = bp['Month, Year of Filled At'].min()
end_date = bp['Month, Year of Filled At'].max()

# -----------------------------
# streamlit stuff begins below
# -----------------------------

bp_tab, tab2 = st.tabs(['buprenorphine', 'tab2'])
if 'counties' not in st.session_state:
    st.session_state['counties'] = ALL_AZ_COUNTIES

with st.sidebar:
        date_range = st.slider(
            'select date', 
            key='date_range_selector', 
            min_value=start_date, 
            value=(start_date, end_date), 
            max_value=end_date,
            format = 'MMM YYYY'
            )
        sc1, sc2 = st.columns([2,1])
        container = sc1.container()
        all = sc2.button('select all')
        if all:
            st.session_state['counties'] = ALL_AZ_COUNTIES
        counties = container.multiselect(
                'select pharmacy counties',
                ALL_AZ_COUNTIES,
                key='counties'
            )      

# handle the date_range input
q_start = date_range[0].replace(day=1)
try:
    q_end = date_range[1].replace(day=1)
except:
    q_end = date_range[0].replace(day=1)

with bp_tab:
    # filter the data using user selections from the sidebar
    bp['Month, Year'] = bp['Month, Year of Filled At'] + pd.Timedelta(days=1) # this is a bit hacky, should really set timezone to fix tooltip display in altair 
    bp = bp[(bp['Month, Year of Filled At'] >= q_start) & (bp['Month, Year of Filled At'] <= q_end)]
    bp = bp[bp['Current Pharmacy County'].str.title().isin(counties)]
    bp.rename(columns={'Current Pharmacy County':'Pharmacy County'}, inplace=True)

    bp_for_line = bp.groupby(['Month, Year', 'Generic Name'])['Prescription Count'].sum().reset_index()

    bp_for_map = bp.copy()
    bp_for_map['Pharmacy County'] = bp_for_map['Pharmacy County'].str.title()
    bp_for_map = bp_for_map.merge(county_codes, how='left', left_on='Pharmacy County', right_on='county').drop(columns=['county'])
    bp_for_map = bp_for_map.groupby(['Pharmacy County', 'county_code'])['Prescription Count'].sum().reset_index()

    # line chart with mouseover interaction
    brush = alt.selection_single(on='mouseover', nearest=True)
    bp_line = alt.Chart(bp_for_line).mark_line().encode(
        alt.X('Month, Year', axis=alt.Axis(format='%Y %B', title='date')),
        alt.Y('Prescription Count', axis=alt.Axis(title='rx count')),
        color=alt.Color('Generic Name', scale=alt.Scale(scheme='accent'), legend=alt.Legend(title=' ', orient='top')), # title is space to prevent an altair bug that causes clipping
        strokeDash='Generic Name',
        strokeWidth=alt.value(3),
        tooltip=['Generic Name', 'Month, Year', 'Prescription Count']
    ).add_selection(
        brush
    )

    # add a line for the day the x dea requirement was removed if the selected date range includes that date
    if (q_end > datetime.strptime(X_DATE, '%Y-%m-%d').date()):
        rules = alt.Chart(pd.DataFrame({
            'Month, Year of Filled At': [X_DATE],
            'color':['white'],
        })).mark_rule().encode(
            x='Month, Year of Filled At:T',
            color=alt.Color('color:N', scale=None)
        )
        chart = bp_line + rules
    else:
        chart = bp_line

    chart = chart.configure_legend(labelLimit=0)

    # USA county map
    counties_map = alt.topo_feature(data.us_10m.url, 'counties')

    map_az = (
        alt.Chart(data = counties_map)
        .mark_geoshape(
            stroke='white'
        ).encode(
            tooltip=['Pharmacy County:N', 'Prescription Count:Q'],
            color=alt.Color('Prescription Count:Q', scale=alt.Scale(scheme='orangered')),
        ).transform_calculate(state_id = 'datum.id / 1000|0').transform_filter((alt.datum.state_id)==4).project(    # map just AZ
            type='mercator'
        ).transform_lookup(
            lookup='id',
            from_=alt.LookupData(bp_for_map, 'county_code', ['county_code','Pharmacy County', 'Prescription Count'])
        )
    )

    # format dataframe for display and downloading
    bp.drop(columns='Month, Year', inplace=True)
    bp['Month, Year of Filled At'] = bp['Month, Year of Filled At'].astype('datetime64[ns]').dt.strftime('%Y-%m')

    # ------------
    # page layout
    # ------------
    chart_col1, chart_col2 = st.columns([5,1])
    chart_col1.altair_chart(chart, theme='streamlit', use_container_width=True)

    csv = convert_df(bp)
    chart_col2.download_button(
        label='download csv',
        data=csv,
        file_name=f'buprenorphine_data_{datetime.strftime(q_start, "%Y-%m")}_to_{datetime.strftime(q_end, "%Y-%m")}.csv',
        mime='text/csv'
    )

    map_col1, map_col2 = st.columns([2,1])
    map_col1.write(bp)
    map_col2.altair_chart(map_az, use_container_width=True)

with tab2:
    st.write('# **:blue[tab2 goes here]**')    
    '''daterange:'''
    st.write(f':orange[{datetime.strftime(q_start, "%Y-%m")}] to :green[{datetime.strftime(q_end, "%Y-%m")}]')
    '''counties:'''
    st.write(counties)