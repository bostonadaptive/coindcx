#!/usr/bin/env python3
"""
Playwright smoke script (Python):
- Opens the app locally
- Signs up / logs in a test user
- Shows dashboard without API creds (paper fallback and banner)
- Optionally runs scripts/_add_creds_smoke.py to add per-user creds
- Reloads the dashboard to show the real-mode response
- Records a short WebM file and exits

Usage (PowerShell):
  python -m pip install playwright
  python -m playwright install
  python scripts\playwright_smoke_record.py --output smoke_demo.webm --add-creds

Note: This script assumes the Flask app is running on http://127.0.0.1:5000
and that the repository root is the current working directory.
"""
import argparse
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def run_add_creds():
    p = subprocess.run(["python", "scripts/_add_creds_smoke.py"], capture_output=True, text=True)
    print('add_creds stdout:', p.stdout)
    print('add_creds stderr:', p.stderr)


def ensure_url(page, url, timeout=10):
    page.goto(url)
    # wait for body to load
    page.wait_for_selector('body', timeout=timeout*1000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='smoke_demo.webm', help='Output recording file (webm)')
    parser.add_argument('--add-creds', action='store_true', help='Run scripts/_add_creds_smoke.py mid-flow')
    args = parser.parse_args()

    app_url = 'http://127.0.0.1:5000'
    signup_email = 'smoke_test_user@example.com'
    signup_password = 'testpass123'

    # Prepare output path
    out_path = Path(args.output).resolve()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(record_video_dir=str(out_path.parent), record_video_size={"width": 1280, "height": 720})
        page = context.new_page()

        # 1) Go to signup and create user (safe if user exists it'll show message)
        ensure_url(page, f'{app_url}/signup')
        # Fill form if visible
        try:
            page.fill('input[name="email"]', signup_email)
            page.fill('input[name="password"]', signup_password)
            page.fill('input[name="confirm_password"]', signup_password)
            page.click('button[type="submit"]')
            # small wait for redirect
            page.wait_for_timeout(1000)
        except Exception:
            # perhaps signup form not present, continue
            pass

        # 2) Login
        ensure_url(page, f'{app_url}/login')
        page.fill('input[name="email"]', signup_email)
        page.fill('input[name="password"]', signup_password)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle')

        # 3) Navigate to dashboard and wait for banner or positions
        ensure_url(page, f'{app_url}/dashboard')
        # give front-end a few seconds to call endpoints and render
        page.wait_for_timeout(2000)

        # 4) If we see the paper fallback banner (id #paperFallbackBanner), keep it on-screen for demo
        try:
            banner = page.query_selector('#paperFallbackBanner')
            if banner:
                print('Paper fallback banner found (initial state)')
        except Exception:
            pass

        # 5) Optionally add credentials in DB to flip the state
        if args.add_creds:
            run_add_creds()
            # reload dashboard
            page.reload()
            page.wait_for_timeout(1500)

        # 6) Let the renderer settle and then stop recording
        page.wait_for_timeout(1000)

        # Save the recorded video (Playwright stores a video file in a temp dir; move it)
        context.close()
        browser.close()

        # Playwright records one video per page in the recording dir; find the newest file
        candidates = list(out_path.parent.glob('**/*.webm'))
        if not candidates:
            print('No recorded video found in', out_path.parent)
            return
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        latest.rename(out_path)
        print('Saved smoke recording to', out_path)


if __name__ == '__main__':
    main()
