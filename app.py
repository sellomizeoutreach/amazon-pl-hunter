"""
Streamlit Cloud Entrypoint for Amazon Private Label & Decision Maker Hunter.
Runs 100% standalone without requiring a separate backend server.
"""
import os
import sys

root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

app_path = os.path.join(root_dir, "dashboard", "app.py")
with open(app_path, "r", encoding="utf-8") as f:
    code = compile(f.read(), app_path, 'exec')
    exec(code)
