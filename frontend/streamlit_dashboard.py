"""
Streamlit dashboard to visualize data from reporter_with_storage.py

To run:
1. Start the server: python reporter_with_storage.py
2. Run this dashboard: streamlit run streamlit_dashboard.py
"""

import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
import numpy as np 

# --- CONFIGURATION ---
REPORTER_URL = "http://localhost:8001/reports"
REFRESH_SECONDS = 5  # How often to fetch new data

st.set_page_config(layout="wide")
st.title("🤖 Live Happiness & Network Dashboard")

def fetch_data():
    """Fetches the complete report list from the server."""
    try:
        response = requests.get(REPORTER_URL)
        response.raise_for_status()  # Raise an error for bad responses (4xx, 5xx)
        return response.json().get('reports', [])
    except requests.exceptions.ConnectionError:
        st.error(f"ConnectionError: Could not connect to the report server at {REPORTER_URL}. Is it running?", icon="🔌")
        return None
    except Exception as e:
        st.error(f"An error occurred while fetching data: {e}", icon="🔥")
        return None

def process_data(reports):
    """Converts the raw report list into a clean Pandas DataFrame."""
    processed_data = []
    
    # Define all columns we want
    cols = [
        'timestamp', 'region', 'short_term_avg', 'long_term_avg', 
        'latency_ms', 'packet_loss_percent', 'short_term_scores',
        'action', 'reasoning'  # <-- NEW
    ]
    
    if not reports:
        return pd.DataFrame(columns=cols)

    for report in reports:
        try:
            timestamp = datetime.fromisoformat(report['received_at'])
            region = report['data']['region']
            data_bundle = report['data'].get('data_bundle', {})
            decision = report['data'].get('decision', {}) # <-- NEW

            # 1. Extract happiness state
            happiness_state = data_bundle.get('happiness_state', {})
            short_term_avg = happiness_state.get('short_term_avg', np.nan)
            long_term_avg = happiness_state.get('long_term_avg', np.nan)
            short_term_scores = happiness_state.get('short_term_scores', [])

            # 2. Extract network metrics
            network_metrics = data_bundle.get('network_metrics', [])
            latency = np.nan
            packet_loss = np.nan
            
            if network_metrics:
                first_metric = network_metrics[0]
                latency = first_metric.get('latency_ms', np.nan)
                packet_loss = first_metric.get('packet_loss_percent', np.nan)

            # 3. Extract decision (NEW)
            action = decision.get('action', 'N/A')
            parameters = decision.get('parameters', {})
            reason = parameters.get('reason')
            summary = parameters.get('summary')
            reasoning = reason or summary or "No details provided." # Gets whichever one exists

            processed_data.append({
                'timestamp': timestamp,
                'region': region,
                'short_term_avg': short_term_avg,
                'long_term_avg': long_term_avg,
                'latency_ms': latency,
                'packet_loss_percent': packet_loss,
                'short_term_scores': short_term_scores,
                'action': action,          # <-- NEW
                'reasoning': reasoning     # <-- NEW
            })
        except Exception as e:
            # Skip reports with processing errors
            print(f"Skipping report due to processing error: {e}")
            pass
            
    df = pd.DataFrame(processed_data)
    if not df.empty:
        df = df.sort_values(by='timestamp')
    return df

def plot_time_series(df, value_column, title):
    """Helper function to pivot, fill, and plot a time series."""
    st.header(f"📈 {title}")
    
    if value_column not in df.columns or df[value_column].isnull().all():
        st.info(f"No data available for {title} yet.")
        return

    try:
        chart_df = df.pivot(index='timestamp', columns='region', values=value_column)
        chart_df = chart_df.ffill()
        st.line_chart(chart_df)
    except Exception as e:
        st.error(f"Could not plot {title}: {e}")

# --- MAIN DASHBOARD LOGIC ---

# Fetch and process data
raw_reports = fetch_data()

if raw_reports is not None:
    df = process_data(raw_reports)

    if df.empty:
        st.info("Waiting for the first report from the server...")
    else:
        # Get a list of all unique regions
        all_regions = df['region'].unique()
        
        # --- 1. Plot all time series charts ---
        plot_time_series(df, 'short_term_avg', 'Time Series: Short-Term Average Happiness')
        plot_time_series(df, 'long_term_avg', 'Time Series: Long-Term Average Happiness')
        plot_time_series(df, 'latency_ms', 'Time Series: Network Latency (ms)')
        plot_time_series(df, 'packet_loss_percent', 'Time Series: Packet Loss (%)')

        st.divider()

        # --- 2. Most Recent "Short-Term Scores" (as bar charts) ---
        st.header("📊 Most Recent: Individual Scores")
        st.info("These charts show the raw scores from the *most recent* report for each region.")

        cols = st.columns(len(all_regions))
        for i, region in enumerate(all_regions):
            with cols[i]:
                st.subheader(region)
                last_report_for_region = df[df['region'] == region].iloc[-1]
                last_scores_list = last_report_for_region['short_term_scores']
                
                if last_scores_list:
                    st.bar_chart(last_scores_list)
                else:
                    st.write("No individual scores in last report.")
        
        st.divider()

        # --- 3. NEW SECTION: Action Log ---
        st.header("📜 Recent Agent Actions")
        st.info("This log shows the most recent decisions made by the agent for each region.")
        
        # Select and rename columns for clarity
        action_df = df[['timestamp', 'region', 'action', 'reasoning']].copy()
        action_df.rename(columns={'reasoning': 'Reason / Summary'}, inplace=True)
        
        # Sort by most recent first
        action_df = action_df.sort_values(by='timestamp', ascending=False)
        
        st.dataframe(action_df, use_container_width=True)

        # --- 4. Raw Data (for debugging) ---
        with st.expander("Show Latest Raw Data (Last 10 Reports)"):
            st.dataframe(df.tail(10))

# --- Auto-refresh logic ---
st.caption(f"Page will refresh in {REFRESH_SECONDS} seconds...")
time.sleep(REFRESH_SECONDS)
st.rerun()