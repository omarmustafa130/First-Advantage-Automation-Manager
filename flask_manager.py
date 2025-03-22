from flask import Flask, render_template, request, redirect, jsonify
from automation_worker import automation_instance
import datetime
import pytz
import threading

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html",
        client_id=automation_instance.CLIENT_ID,
        user_id=automation_instance.USER_ID,
        processed=automation_instance.processed,
        total=automation_instance.total,
        status=automation_instance.get_status()
    )

@app.route('/update', methods=['POST'])
def update():
    automation_instance.update_credentials(
        request.form['client_id'],
        request.form['user_id'],
        request.form['password'],
        request.form['security_question'],
        request.form['sheet_url']
    )
    return redirect("/")

@app.route('/start', methods=['POST'])
def start_now():
    gmt5 = pytz.timezone("Etc/GMT+5")  # GMT-5 (Eastern Time)
    now = datetime.datetime.now(gmt5)
    if 8 <= now.hour < 20:
        automation_instance.run()
    else:
        automation_instance.set_status("Sleeping until 8am GMT-5")
        wait_seconds = ((24 + 8 - now.hour) % 24) * 3600 - now.minute * 60 - now.second
        threading.Timer(wait_seconds, automation_instance.run).start()
    return redirect("/")


@app.route('/stop', methods=['POST'])
def stop_now():
    automation_instance.stop()
    return redirect("/")

@app.route('/status')
def status():
    remaining = max(automation_instance.total - automation_instance.processed, 0)
    estimated_seconds = remaining * 75
    eta_minutes = estimated_seconds // 60
    eta_seconds = estimated_seconds % 60
    eta = f"{int(eta_minutes)}m {int(eta_seconds)}s" if remaining else "0m 0s"

    status_data = automation_instance.get_status()
    return jsonify({
        "processed": status_data["processed"],
        "total": status_data["total"],
        "client_id": status_data["client_id"],
        "user_id": status_data["user_id"],
        "sheet_url": status_data["sheet_url"],
        "status": status_data["status"],
        "eta": eta
    })

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001)
