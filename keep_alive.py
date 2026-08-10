import os
import threading
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)
start_time = datetime.utcnow()

BOT_NAME = "Cricket Stats Bot"

@app.route("/")
def index():
    uptime = datetime.utcnow() - start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{BOT_NAME} — Status</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', sans-serif;
      background: #0d1117;
      color: #e6edf3;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .card {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 16px;
      padding: 48px 56px;
      text-align: center;
      max-width: 440px;
      width: 100%;
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }}
    .pulse {{
      display: inline-block;
      width: 14px;
      height: 14px;
      background: #2ea043;
      border-radius: 50%;
      margin-right: 8px;
      animation: pulse 1.6s ease-in-out infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ box-shadow: 0 0 0 0 rgba(46,160,67,0.5); }}
      50% {{ box-shadow: 0 0 0 8px rgba(46,160,67,0); }}
    }}
    h1 {{ font-size: 1.6rem; margin-bottom: 8px; }}
    .status {{
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1rem;
      color: #2ea043;
      font-weight: 600;
      margin-bottom: 32px;
    }}
    .stats {{
      background: #0d1117;
      border-radius: 10px;
      padding: 20px 24px;
      text-align: left;
    }}
    .stat-row {{
      display: flex;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid #21262d;
      font-size: 0.92rem;
    }}
    .stat-row:last-child {{ border-bottom: none; }}
    .stat-label {{ color: #8b949e; }}
    .stat-value {{ color: #e6edf3; font-weight: 500; }}
    .cricket {{ font-size: 2.4rem; margin-bottom: 16px; }}
    .footer {{ margin-top: 24px; font-size: 0.78rem; color: #484f58; }}
  </style>
  <meta http-equiv="refresh" content="30"/>
</head>
<body>
  <div class="card">
    <div class="cricket">🏏</div>
    <h1>{BOT_NAME}</h1>
    <div class="status"><span class="pulse"></span>Online</div>
    <div class="stats">
      <div class="stat-row">
        <span class="stat-label">Uptime</span>
        <span class="stat-value">{uptime_str}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Started</span>
        <span class="stat-value">{start_time.strftime('%Y-%m-%d %H:%M')} UTC</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Status</span>
        <span class="stat-value" style="color:#2ea043;">Running</span>
      </div>
    </div>
    <div class="footer">Page auto-refreshes every 30 seconds</div>
  </div>
</body>
</html>"""
    return html


@app.route("/health")
def health():
    return jsonify({"status": "ok", "bot": BOT_NAME}), 200


def run():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def keep_alive():
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
