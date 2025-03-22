import os
import subprocess
import sys

REQUIREMENTS = [
    "flask",
    "playwright",
    "gspread",
    "oauth2client",
    "apscheduler"
]

def run(command):
    print(f"▶ Running: {command}")
    result = subprocess.run(command, shell=True)
    if result.returncode != 0:
        print(f"❌ Command failed: {command}")
        sys.exit(result.returncode)

def main():
    python_path = sys.executable
    pip_path = os.path.join(os.path.dirname(python_path), "pip")

    print(f"📦 Using pip: {pip_path}")
    print(f"🐍 Using python: {python_path}")

    print("📦 Upgrading pip...")
    run(f'"{pip_path}" install --upgrade pip')

    print("📦 Installing dependencies...")
    for pkg in REQUIREMENTS:
        run(f'"{pip_path}" install {pkg}')

    print("🌐 Installing Playwright browsers...")
    run(f'"{python_path}" -m playwright install chromium')

    print("\n✅ All done! Your environment is ready.")

if __name__ == "__main__":
    main()
