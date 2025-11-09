# --- agent_listener.py ---
# (Run this in a *separate* terminal from your simulator)

import requests
import json
import time
import os
import sys
from dotenv import load_dotenv

# --- 1. CONFIGURATION ---

# The address of your simulator's web server
SIMULATOR_URL = "http://localhost:8000"

# --- NEW ADDITION: Address for your 2nd server to *receive* reports ---
REPORTING_SERVER_URL = "http://localhost:8001" 
# --- END NEW ADDITION ---

# Load API keys from .env file
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    print("Error: OPENROUTER_API_KEY not found. Please set it in a .env file.")
    sys.exit(1)

# The specific model identifier on OpenRouter
NEMOTRON_MODEL_ID = "nvidia/nemotron-nano-9b-v2" # Using Nano 9B as requested

# --- 2. OPENROUTER API CLIENT (THE "BRAIN" CONNECTOR) ---

def call_nemotron(prompt, return_json=False):
    """
    A generic function to call the Nemotron model via OpenRouter.
    """
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": NEMOTRON_MODEL_ID,
                "messages": [{"role": "user", "content": prompt}],
                # Request JSON output if needed
                "response_format": {"type": "json_object"} if return_json else None
            }
        )
        
        if response.status_code != 200:
            print(f"Error calling Nemotron: {response.status_code} - {response.text}")
            return None

        content = response.json()['choices'][0]['message']['content']
        
        if return_json:
            # Parse the JSON string from the model's content
            return json.loads(content)
        else:
            return content

    except Exception as e:
        print(f"An error occurred during the Nemotron API call: {e}")
        return None

# --- 3. AGENT 1: "PERCEPTION" AGENT ---

def get_event_analysis(text):
    """
    Uses Nemotron to analyze text for sentiment, topic, and urgency.
    """
    print(f"🧠 [Agent 1] Analyzing text: '{text[:50]}...'")
    
    prompt = f"""
    You are a sentiment analysis expert. Analyze the following customer text. 
    Respond with a single JSON object containing:
    1. "sentiment": "positive", "negative", or "neutral".
    2. "topic": "network_signal", "billing", "customer_service", "app_functionality", or "other".
    3. "urgency": "high", "medium", or "low".

    Text: "{text}"
    """
    
    analysis = call_nemotron(prompt, return_json=True)
    if analysis:
        print(f"✅ [Agent 1] Analysis complete: {analysis}")
    return analysis

# --- 4. AGENT 2/LT: "HAPPINESS TRACKER" AGENT (STATEFUL) ---

class HappinessTracker:
    """
    A stateful agent that calculates short-term and long-term happiness
    for each region using a dual moving average.
    """
    # Faster window for conclusions
    SHORT_TERM_WINDOW = 10   # Was 20
    LONG_TERM_WINDOW = 100   # Was 100
    GRAPH_HISTORY_LENGTH = 50 # How many data points to show on the graph
    
    def __init__(self):
        self.regions = {}

    def _get_or_create_region(self, region):
        """Initializes a new region if it's the first time we see it."""
        if region not in self.regions:
            self.regions[region] = {
                "short_term_scores": [],
                "long_term_scores": [],
                "short_term_avg": 0,
                "long_term_avg": 0,
                "was_above": None, # For crossover detection
                "state": "MAINTAIN_NEUTRAL",
                "history": [] # Added history for graphing
            }
        return self.regions[region]

    def _update_state(self, region_data):
        """Updates the region's label based on moving average crossovers."""
        sma = region_data["short_term_avg"]
        lma = region_data["long_term_avg"]
        is_above = sma > lma
        
        # Only update state if LMA has enough data to be meaningful
        if len(region_data["long_term_scores"]) < self.LONG_TERM_WINDOW:
            region_data["state"] = "PRIMING" # State before we "trust" the label
            return

        # Initialize on first run after priming
        if region_data["was_above"] is None:
            region_data["was_above"] = is_above
            return

        # Check for crossovers
        if is_above and not region_data["was_above"]:
            region_data["state"] = "TRENDING_UP" # Golden Cross
        elif not is_above and region_data["was_above"]:
            region_data["state"] = "TRENDING_DOWN" # Death Cross
        # No crossover, maintain state based on position
        elif is_above:
            region_data["state"] = "MAINTAIN_GOOD"
        else:
            region_data["state"] = "MAINTAIN_POOR"
        
        region_data["was_above"] = is_above

    def add_sentiment_score(self, region, score):
        """Adds a new score and recalculates averages and state."""
        region_data = self._get_or_create_region(region)
        
        # Update short-term
        region_data["short_term_scores"].append(score)
        if len(region_data["short_term_scores"]) > self.SHORT_TERM_WINDOW:
            region_data["short_term_scores"].pop(0)
        
        # Update long-term
        region_data["long_term_scores"].append(score)
        if len(region_data["long_term_scores"]) > self.LONG_TERM_WINDOW:
            region_data["long_term_scores"].pop(0)

        # Recalculate averages
        if region_data["short_term_scores"]:
            region_data["short_term_avg"] = sum(region_data["short_term_scores"]) / len(region_data["short_term_scores"])
        if region_data["long_term_scores"]:
            region_data["long_term_avg"] = sum(region_data["long_term_scores"]) / len(region_data["long_term_scores"])
            
        # Update the long-term state label
        self._update_state(region_data)
        
        # Save data point for the graph
        region_data["history"].append(region_data["short_term_avg"])
        if len(region_data["history"]) > self.GRAPH_HISTORY_LENGTH:
            region_data["history"].pop(0)

        print(f"📈 [State Agent] {region} Happiness: [Short: {region_data['short_term_avg']:.2f}, Long: {region_data['long_term_avg']:.2f}, State: {region_data['state']}]")

    def get_region_snapshot(self, region):
        """Gets all current data for a region."""
        return self._get_or_create_region(region).copy()

# --- 5. AGENT 4: "ORCHESTRATOR" AGENT ---

def get_proactive_decision(region_name, data_bundle):
    """
    Uses Nemotron to make a high-level decision based on all available data.
    """
    print(f"\n🤔 [Agent 4] Making proactive decision for {region_name}...")
    
    # Cleanly format the data for the prompt
    prompt_data = json.dumps(data_bundle, indent=2)
    
    prompt = f"""
    You are a T-Mobile Operations Manager. Analyze the following real-time data 
    from the '{region_name}' region and decide on a single, proactive action.
    The 'state' is 'PRIMING' until 10 events are received. After 10 events,
    'MAINTAIN_GOOD' or 'MAINTAIN_POOR' are trusted labels.

    DATA:
    {prompt_data}

    Available Actions (Tools):
    1. send_alert(team, summary, priority): 
       (Teams: 'NetworkOps', 'BillingSupport', 'Marketing', 'AppDev')
       (Priority: 'P0', 'P1', 'P2', 'P3')
    2. draft_social_reply(original_text, key_points): 
       (Drafts a reply for a human to review. Use for high-urgency public posts.)
    3. log_and_monitor(reason): 
       (If the issue is minor or 'PRIMING'. 'reason' explains why.)

    Your Task: Respond *only* with the JSON for the single best action to take.
    Example: {{"action": "send_alert", "parameters": {{"team": "NetworkOps", "summary": "...", "priority": "P1"}}}}
    """
    
    decision = call_nemotron(prompt, return_json=True)
    return decision

# --- 6. SIMULATOR DATA FETCHER (FROM YOUR SCRIPT) ---

def fetch_latest_data():
    """Fetches the latest batch of events from the simulator."""
    try:
        response = requests.get(SIMULATOR_URL)
        if response.status_code == 200:
            events = response.json()
            return events
        else:
            print(f"Error: Server returned status code {response.status_code}")
            return None
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the simulator. Is simulator.py running?")
        return None
    except json.JSONDecodeError:
        print("Error: Received invalid JSON from the server.")
        return None

# --- NEW ADDITION: Function to send reports to a second server ---
def send_report_to_server(report_data):
    """
    Sends the agent's final decision to the reporting server.
    """
    if not report_data:
        return
        
    print(f"📤 [Action Agent] Sending report to {REPORTING_SERVER_URL}...")
    try:
        response = requests.post(REPORTING_SERVER_URL, json=report_data)
        if response.status_code == 200:
            print(f"✅ [Action Agent] Report successfully sent.")
        else:
            print(f"❗️ [Action Agent] Reporting server returned status {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print(f"❗️ [Action Agent] FAILED to connect to reporting server at {REPORTING_SERVER_URL}.")
        print("   Is your second server running?")
    except Exception as e:
        print(f"❗️ [Action Agent] An unknown error occurred while sending report: {e}")
# --- END NEW ADDITION ---


# --- ASCII Graphing Function ---
def print_happiness_graphs(tracker):
    """
    Prints simple ASCII line graphs for the short-term happiness
    of each region to the console.
    """
    print("\n" + "="*50)
    print(f"📊 60-SECOND HAPPINESS REPORT ({time.strftime('%H:%M:%S')}) 📊")
    print("="*50)
    
    GRAPH_WIDTH = 40
    POSITIVE_CHAR = '█'
    NEGATIVE_CHAR = '░'
    ZERO_CHAR = '─'

    for region, data in tracker.regions.items():
        if not data["history"]:
            continue
            
        print(f"\nRegion: {region} (State: {data['state']})")
        print(f"  (Negative) <{' '*(GRAPH_WIDTH//2 - 2)} 0 {' '*(GRAPH_WIDTH//2 - 2)}> (Positive)")
        
        def scale_value_to_graph(value):
            scaled = int((value + 1) / 2 * GRAPH_WIDTH)
            return max(0, min(scaled, GRAPH_WIDTH))

        zero_point = scale_value_to_graph(0)
        
        for val in data["history"]:
            graph_line = [' '] * (GRAPH_WIDTH + 1)
            pos = scale_value_to_graph(val)
            
            if pos > zero_point:
                for i in range(zero_point, pos + 1):
                    graph_line[i] = POSITIVE_CHAR
            elif pos < zero_point:
                for i in range(pos, zero_point):
                    graph_line[i] = NEGATIVE_CHAR
            
            graph_line[zero_point] = ZERO_CHAR # Draw the zero axis
            print(f"  {''.join(graph_line)} | {val: .2f}")
    print("\n" + "="*50)


# --- 7. MAIN AGENTIC LOOP ---

def main():
    print("--- 🚀 Real-Time AGENTIC Listener START ---")
    print(f"Polling {SIMULATOR_URL} every 5 seconds...")
    print("Press Ctrl+C to stop.\n")
    
    tracker = HappinessTracker()
    start_time = time.time()
    last_plot_time = start_time
    GRAPH_INTERVAL_SECONDS = 60
    
    try:
        while True:
            events = fetch_latest_data()
            
            if not events:
                time.sleep(5)
                continue
                
            print(f"\n--- Received {len(events)} new events at {time.strftime('%H:%M:%S')} ---")
            
            # --- LOOP 1: PERCEIVE & ANALYZE ---
            grouped_data = {}
            for event in events:
                region = event.get('region')
                if not region:
                    continue 
                
                if region not in grouped_data:
                    grouped_data[region] = {
                        "network_metrics": [],
                        "analyzed_posts": []
                    }
                
                etype = event['event_type']
                if etype == 'network_metric':
                    grouped_data[region]["network_metrics"].append(event)
                elif etype in ('social_media_post', 'support_interaction'):
                    text = event.get('text') or event.get('log')
                    if not text:
                        continue
                        
                    analysis = get_event_analysis(text)
                    if analysis:
                        score_map = {'positive': 1, 'negative': -1, 'neutral': 0}
                        score = score_map.get(analysis.get('sentiment', 'neutral'), 0)
                        tracker.add_sentiment_score(region, score)
                        event['analysis'] = analysis
                        grouped_data[region]["analyzed_posts"].append(event)
            
            # --- LOOP 2: DECIDE & ACT ---
            for region, data in grouped_data.items():
                if region == 'global' or (not data['network_metrics'] and not data['analyzed_posts']):
                    continue 
                
                happiness_snapshot = tracker.get_region_snapshot(region)
                final_bundle = {
                    "happiness_state": happiness_snapshot,
                    "network_metrics": data['network_metrics'],
                    "recent_posts": data['analyzed_posts']
                }
                
                decision = get_proactive_decision(region, final_bundle)
                
                print(f"--- 💡 FINAL ACTION for {region} ---")
                if decision:
                    print(json.dumps(decision, indent=2))
                    
                    # --- NEW ADDITION: Send the report to the second server ---
                    # We send the decision *and* the data that led to it
                    full_report = {
                        "region": region,
                        "decision": decision,
                        "data_bundle": final_bundle
                    }
                    send_report_to_server(full_report)
                    # --- END NEW ADDITION ---
                    
                else:
                    print("No decision was returned from the agent.")
                print("-" * 40 + "\n")
            
            
            # --- Check timer and print graph ---
            current_time = time.time()
            if current_time - last_plot_time > GRAPH_INTERVAL_SECONDS:
                print_happiness_graphs(tracker)
                last_plot_time = current_time # Reset timer

            # Wait for the next tick (matches your simulator)
            time.sleep(5) 
            
    except KeyboardInterrupt:
        print("\n--- 🛑 Agentic Listener Stopped ---")

if __name__ == "__main__":
    main()