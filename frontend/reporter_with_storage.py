"""
Modified reporter.py with data storage for Streamlit dashboard
Save this as: reporter_with_storage.py
"""

import http.server
import socketserver
import json
import time
from collections import deque
from datetime import datetime
import threading

# --- CONFIGURATION ---
PORT = 8001
MAX_HISTORY = 200  # Keep last 200 reports

# Shared data store (thread-safe with a lock)
data_store = {
    'reports': deque(maxlen=MAX_HISTORY),
    'lock': threading.Lock()
}

class MyReportHandler(http.server.BaseHTTPRequestHandler):
    """Request handler that stores incoming reports"""
    
    def _send_response(self, status_code, message):
        """Helper to send a JSON response."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*') 
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(message).encode('utf-8'))

    def do_GET(self):
        """
        NEW: Handle GET requests to retrieve stored reports
        Streamlit will call this endpoint to get data
        """
        if self.path == '/reports':
            try:
                with data_store['lock']:
                    # Convert deque to list for JSON serialization
                    reports_list = list(data_store['reports'])
                
                self._send_response(200, {
                    "status": "ok",
                    "count": len(reports_list),
                    "reports": reports_list
                })
            except Exception as e:
                print(f"❗️ Error processing GET request: {e}")
                self._send_response(500, {"status": "error", "message": str(e)})
        else:
            self._send_response(404, {"status": "error", "message": "Not found"})

    def do_POST(self):
        """Handles incoming POST requests and stores them"""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data_bytes = self.rfile.read(content_length)
            post_data_json = json.loads(post_data_bytes.decode('utf-8'))
            
            # Add server timestamp and wrap the received data
            report_with_timestamp = {
                'received_at': datetime.now().isoformat(),
                'data': post_data_json  # <--- This is the key part
            }
            
            # Store the report (thread-safe)
            with data_store['lock']:
                data_store['reports'].append(report_with_timestamp)
            
            # Print to console
            print("\n" + "="*50)
            print(f"✅ RECEIVED REPORT at {time.strftime('%H:%M:%S')}")
            print("="*50)
            print(json.dumps(post_data_json, indent=2))
            print("="*50 + "\n")
            
            self._send_response(200, {"status": "ok", "message": "Report received"})
        
        except Exception as e:
            print(f"❗️ Error processing POST request: {e}")
            self._send_response(500, {"status": "error", "message": str(e)})

    def do_OPTIONS(self):
        """Handles OPTIONS pre-flight requests"""
        self._send_response(200, {"status": "ok"})
    
    def log_message(self, format, *args):
        """Suppress default HTTP logging"""
        pass

def run_server():
    """Starts the server"""
    try:
        with socketserver.TCPServer(("", PORT), MyReportHandler) as httpd:
            print(f"--- 🚀 Report Server START ---")
            print(f"Listening on http://localhost:{PORT}")
            print(f"GET  http://localhost:{PORT}/reports - Fetch stored reports")
            print(f"POST http://localhost:{PORT} - Receive new reports")
            httpd.serve_forever()
            
    except OSError:
        print(f"--- ❗️ COULD NOT START SERVER on port {PORT}. Is it already in use? ---")
    except KeyboardInterrupt:
        print("\n--- 🛑 Report Server Stopped ---")

if __name__ == "__main__":
    run_server()