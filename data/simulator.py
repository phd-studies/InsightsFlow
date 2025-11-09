import google.generativeai as genai
import os
import time
import random
import json
import sys
import threading
import http.server
import socketserver
from dotenv import load_dotenv

# --- 1. DEFINE REGION PROFILES ---
# We've added a "display_name" key for the clean JSON output.
REGION_PROFILES = [
    {
        "name": "Dallas (Good Signal, Bad Sentiment)",
        "display_name": "Dallas", # Clean name for output
        "type": "anomaly_good", 
        "network": {"latency_range": (20.0, 80.0), "loss_range": (0.0, 0.5), "spike_chance": 0.01},
        "prompt_bias": "The sentiment should be surprisingly mostly neutral and some negative, despite good signal. Topics are about billing issues, poor customer service, or confusing promotions. Users are frustrated with the company, not the signal."
    },
    {
        "name": "New York (Good)",
        "display_name": "New York", # Clean name for output
        "type": "good",
        "network": {"latency_range": (30.0, 90.0), "loss_range": (0.0, 0.6), "spike_chance": 0.02},
        "prompt_bias": "The sentiment should be mostly positive or neutral. Topics are about reliable coverage in a busy city."
    },
    {
        "name": "Chicago (Neutral)",
        "display_name": "Chicago", # Clean name for output
        "type": "neutral",
        "network": {"latency_range": (50.0, 150.0), "loss_range": (0.5, 1.5), "spike_chance": 0.05},
        "prompt_bias": "The sentiment can be positive, negative, or neutral. Topics are mixed: some complaints about spotty downtown coverage, some praise for suburban speeds."
    },
    {
        "name": "Rural Iowa (Poor)",
        "display_name": "Rural Iowa", # Clean name for output
        "type": "poor",
        "network": {"latency_range": (150.0, 500.0), "loss_range": (1.5, 5.0), "spike_chance": 0.20},
        "prompt_bias": "The sentiment should be mostly negative or neutral. Topics are almost always complaints about dropped calls, no signal, or slow data."
    }
]

# --- 2. WEB SERVER SETUP ---
# Global variable to hold the latest JSON data for the web server
LATEST_EVENTS_JSON = "[]"
# Thread-safe lock
EVENTS_LOCK = threading.Lock()

class MyRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    A simple HTTP request handler that serves the latest JSON data.
    """
    def do_GET(self):
        global LATEST_EVENTS_JSON
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*") # Good for hackathons
        self.end_headers()
        
        # Read the global variable in a thread-safe way
        with EVENTS_LOCK:
            json_payload = LATEST_EVENTS_JSON
        
        self.wfile.write(json_payload.encode('utf-8'))

def start_web_server(port=8000):
    """
    Starts the HTTP server in a separate, daemon thread.
    """
    try:
        httpd = socketserver.TCPServer(("", port), MyRequestHandler)
        print(f"--- 🌐 Serving real-time data at http://localhost:{port} ---")
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True # This allows the program to exit
        server_thread.start()
    except OSError:
        print(f"--- ❗️ COULD NOT START WEB SERVER on port {port}. Is it already in use? ---")
        print("Simulator will run without the web server.")

# --- 3. GENERATOR FUNCTIONS (MODIFIED) ---

def generate_network_metrics(region_profile):
    """Generates a network metric event based on a region's profile."""
    profile = region_profile["network"]
    
    latency = random.uniform(*profile["latency_range"])
    packet_loss = random.uniform(*profile["loss_range"])
    
    if random.random() < profile["spike_chance"]:
        latency = random.uniform(latency * 2, latency * 5)
        packet_loss = random.uniform(packet_loss * 2, packet_loss * 5)

    return {
        "event_type": "network_metric",
        "region": region_profile["display_name"], # MODIFIED
        "timestamp": time.time(),
        "latency_ms": round(latency, 2),
        "packet_loss_percent": round(packet_loss, 2)
    }

def generate_app_crash():
    """Has a small chance of generating a global app crash event."""
    if random.random() < 0.005: 
        return {
            "event_type": "app_crash",
            "region": "global", # Unchanged
            "timestamp": time.time(),
            "platform": random.choice(['iOS', 'Android']),
            "app_version": random.choice(['10.1.2', '10.1.1', '10.0.4'])
        }
    return None

def generate_tweet(model, region_profile):
    """Generates a simulated tweet using Gemini, biased by region."""
    
    # The prompt still uses the internal "name" for context
    prompt = f"""
    You are a social media user from {region_profile['name']}. 
    Generate one single, realistic tweet about T-Mobile. 
    The tweet must be short, like a real tweet, and include a relevant hashtag.
    
    Apply this regional bias: {region_profile['prompt_bias']}
    """
    try:
        response = model.generate_content(prompt, safety_settings={'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE'})
        return {
            "event_type": "social_media_post",
            "region": region_profile["display_name"], # MODIFIED
            "timestamp": time.time(),
            "source": "X (Twitter)",
            "text": response.text.strip()
        }
    except Exception as e:
        print(f"Error generating tweet: {e}")
        return None

def generate_support_interaction(model, region_profile):
    """Generates a simulated support interaction, biased by region."""
    
    if region_profile["type"] == "poor":
        issue_topics = "a network outage, poor signal, or dropped calls"
    elif region_profile["type"] == "neutral":
        issue_topics = "a billing question, spotty network, or upgrade eligibility"
    elif region_profile["type"] == "anomaly_good":
        issue_topics = "a complex billing dispute, a promotion not being applied, or a rude customer service agent"
    else: # "good"
        issue_topics = "a simple billing question, upgrade eligibility, or an international plan"

    # The prompt still uses the internal "name" for context
    prompt = f"""
    You are a customer experience simulator. Generate a single, short, simulated 
    T-Mobile customer service interaction from the {region_profile['name']} region.
    Randomly pick one format: [short email, chat log, or phone call transcript summary]. 
    
    The issue must be about: [{issue_topics}]. 
    
    Create both the customer's query and a brief, simulated agent response. 
    Output it as a single block of text.
    """
    try:
        response = model.generate_content(prompt, safety_settings={'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE'})
        return {
            "event_type": "support_interaction",
            "region": region_profile["display_name"], # MODIFIED
            "timestamp": time.time(),
            "channel": random.choice(['email', 'chat', 'phone']),
            "log": response.text.strip()
        }
    except Exception as e:
        print(f"Error generating support log: {e}")
        return None

# --- 4. MAIN SIMULATOR LOOP (MODIFIED) ---
def main():
    
    global LATEST_EVENTS_JSON # Make this accessible
    
    # --- Config ---
    TICK_INTERVAL_SECONDS = 5 
    
    # --- Setup ---
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found. Please set it in a .env file.")
        return
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-flash-lite-latest') # Using Flash for speed
    
    print(f"--- 🚀 T-Mobile Real-Time Simulator START 🚀 ---")
    
    # --- START WEB SERVER ---
    start_web_server()
    
    print(f"\nGenerating new data every {TICK_INTERVAL_SECONDS} seconds...")
    print(f"Press Ctrl+C to stop.")
    
    start_time = time.time()
    tick_count = 0

    try:
        while True:
            tick_count += 1
            elapsed_time = round(time.time() - start_time, 1)
            
            print(f"\n--- TICK {tick_count} (Running for: {elapsed_time}s) ---")
            
            all_events = []
            
            # --- Region-Specific Events ---
            for region in REGION_PROFILES:
                all_events.append(generate_network_metrics(region))
                if tick_count % 3 == 0:
                    print(f"Generating Tweet for {region['display_name']}...")
                    tweet = generate_tweet(model, region)
                    if tweet:
                        all_events.append(tweet)
                if tick_count % 10 == 0:
                    print(f"Generating Support Log for {region['display_name']}...")
                    support_log = generate_support_interaction(model, region)
                    if support_log:
                        all_events.append(support_log)
            
            # --- Global Events ---
            crash = generate_app_crash()
            if crash:
                all_events.append(crash)

            # --- UPDATE WEB SERVER DATA (THREAD-SAFE) ---
            with EVENTS_LOCK:
                LATEST_EVENTS_JSON = json.dumps(all_events, indent=2)

            # --- CONSOLE OUTPUT ---
            for event in all_events:
                print(json.dumps(event, indent=2))
                print("---") 

            time.sleep(TICK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(f"\n\n--- 🛑 SIMULATOR STOPPED BY USER ---")
        print(f"Total runtime: {round(time.time() - start_time, 1)} seconds.")
        sys.exit(0)
    except Exception as e:
        print(f"\n--- ❗️ CRITICAL ERROR ---")
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()