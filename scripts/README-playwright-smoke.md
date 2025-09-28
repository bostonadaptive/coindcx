Playwright smoke demo
======================

This helper records a short browser flow showing the dashboard fallback to paper positions when per-user API credentials are missing, and then (optionally) shows real-mode after adding credentials.

Prerequisites
-------------
- Python 3.8+ in your PATH
- Playwright for Python

Install Playwright (PowerShell):

```powershell
python -m pip install --upgrade pip
python -m pip install playwright
python -m playwright install
```

Run the Flask app (in a separate terminal) from the project root. Ensure the app is reachable at http://127.0.0.1:5000

Run the smoke recording (PowerShell):

```powershell
# Record only the fallback (no DB creds added):
python scripts\playwright_smoke_record.py --output smoke_demo_fallback.webm

# Record fallback then add fake creds (script will call scripts/_add_creds_smoke.py):
python scripts\playwright_smoke_record.py --output smoke_demo_full.webm --add-creds
```

Output
------
The script will produce the specified WebM file in the current directory.

Notes
-----
- The script assumes the app is running at http://127.0.0.1:5000.
- The test user used is `smoke_test_user@example.com` with password `testpass123`.
- `scripts/_add_creds_smoke.py` is a dev helper and writes fake credentials to the local DB; only use in development.
