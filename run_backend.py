import sys
import os
import uvicorn

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.server import app

if __name__ == "__main__":
    print("============================================================")
    print(" Amazon PL Extractor - Standalone Backend Server (Port 8000)")
    print(" Keep this window open while using the Chrome Extension.")
    print("============================================================\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
