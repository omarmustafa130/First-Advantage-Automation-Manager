from flask import Flask, render_template, request, redirect, jsonify
from automation_worker import automation_instance
import pytz
import threading
from datetime import datetime, timedelta, time

app = Flask(__name__)

@app.route('/')
def index():
    status_data = automation_instance.get_status()
    return render_template("index.html",
        client_id=status_data["client_id"],
        user_id=status_data["user_id"],
        processed=status_data["applicants_processed"],
        total=status_data["applicants_total"],
        status=status_data
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
    est = pytz.timezone('US/Eastern')
    now = datetime.now(est)
    
    if 8 <= now.hour < 20:
        automation_instance.run()
    else:
        # Remove this line: automation_instance.set_status("Sleeping until 8am GMT-5")
        automation_instance.stop()  # Ensure any existing process stops
        automation_instance.set_status("Sleeping until 8am EST")
        
        # Calculate time until next 8am
        next_run = est.localize(datetime.combine(
            now.date() + timedelta(days=1 if now.hour >= 20 else 0),
            time(8, 0)
        ))
        wait_seconds = (next_run - now).total_seconds()
        
        threading.Timer(wait_seconds, automation_instance.run).start()
    
    return redirect("/")


@app.errorhandler(500)
def internal_error(error):
    return "Internal server error", 500

@app.route('/stop', methods=['POST'])
def stop_now():
    automation_instance.stop()
    return redirect("/")

@app.route('/force-start', methods=['POST'])
def force_start():
    automation_instance.run(force=True)
    return redirect("/")

@app.route('/status')
def status():
    status_data = automation_instance.get_status()
    remaining = max(status_data["applicants_total"] - status_data["applicants_processed"], 0)
    est = pytz.timezone('US/Eastern')
    current_time = datetime.now(est).strftime("%Y-%m-%d %H:%M:%S ET")
    estimated_seconds = remaining * 75
    eta_minutes = estimated_seconds // 60
    eta_seconds = estimated_seconds % 60
    eta = f"{int(eta_minutes)}m {int(eta_seconds)}s" if remaining else "0m 0s"

    status_data = automation_instance.get_status()

    eta_applicants = f"{(max(status_data['applicants_total'] - status_data['applicants_processed'], 0) * 75) // 60}m"
    eta_pending = f"{(max(status_data['pending_total'] - status_data['pending_processed'], 0) * 75) // 60}m"

    return jsonify({
        "current_time": current_time,
        "client_id": status_data["client_id"],
        "user_id": status_data["user_id"],
        "sheet_url": status_data["sheet_url"],
        "status": status_data["status"],
        "applicants_processed": status_data["applicants_processed"],
        "applicants_total": status_data["applicants_total"],
        "pending_processed": status_data["pending_processed"],
        "pending_total": status_data["pending_total"],
        "orders_placed": status_data["orders_placed"],
        "eta_applicants": eta_applicants,
        "eta_pending": eta_pending
    })


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001)
