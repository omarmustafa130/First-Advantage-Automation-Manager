from flask import Flask, render_template, request, redirect, jsonify
from automation_worker import automation_instance
from apscheduler.schedulers.background import BackgroundScheduler
import datetime

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

schedule_status = {
    "mode": None,
    "time": None
}

@app.route('/')
def index():
    return render_template("index.html",
        client_id=automation_instance.CLIENT_ID,
        user_id=automation_instance.USER_ID,
        processed=automation_instance.processed,
        total=automation_instance.total,
        status=automation_instance.get_status(),
        schedule_info=get_schedule_info()
    )

@app.route('/update', methods=['POST'])
def update():
    automation_instance.update_credentials(
        request.form['client_id'],
        request.form['user_id'],
        request.form['password'],
        request.form['security_question'],
        request.form['sheet_url']  # <-- use raw URL now
    )
    return redirect("/")

@app.route('/start', methods=['POST'])
def start_now():
    automation_instance.run()
    schedule_status["mode"] = None
    schedule_status["time"] = None
    return redirect("/")

@app.route('/stop', methods=['POST'])
def stop_now():
    automation_instance.stop()
    return redirect("/")

@app.route('/schedule', methods=['POST'])
def schedule():
    mode = request.form['mode']
    time_str = request.form['time']
    schedule_status["mode"] = mode
    schedule_status["time"] = time_str
    
    if mode == "once":
        dt = datetime.datetime.strptime(request.form['datetime'], '%Y-%m-%dT%H:%M')
        scheduler.add_job(start_now_background, 'date', run_date=dt)
    elif mode == "daily":
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_job(start_now_background, 'cron', hour=hour, minute=minute)
    elif mode == "weekly":
        weekday = request.form['weekday']
        hour, minute = map(int, time_str.split(":"))
        scheduler.add_job(start_now_background, 'cron', day_of_week=weekday, hour=hour, minute=minute)

    return redirect("/")

def start_now_background():
    automation_instance.run()

def get_schedule_info():
    if schedule_status["mode"]:
        return f"Scheduled to run ({schedule_status['mode']}) at {schedule_status['time']}"
    return ""

@app.route('/status')
def status():
    remaining = max(automation_instance.total - automation_instance.processed, 0)
    estimated_seconds = remaining * 75
    eta_minutes = estimated_seconds // 60
    eta_seconds = estimated_seconds % 60
    eta = f"{int(eta_minutes)}m {int(eta_seconds)}s" if remaining else "0m 0s"

    status_data = automation_instance.get_status()  # Flattened access

    return jsonify({
        "processed": status_data["processed"],
        "total": status_data["total"],
        "client_id": status_data["client_id"],
        "user_id": status_data["user_id"],
        "sheet_url": status_data["sheet_url"],
        "status": status_data["status"],  # string, not a dict
        "schedule": get_schedule_info(),
        "eta": eta
    })


def convert_to_csv_link(url):
    if "/edit" in url:
        url = url.split("/edit")[0]
    if "/pub" in url:
        url = url.split("/pub")[0]
    return f"{url}/export?format=csv"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001)
