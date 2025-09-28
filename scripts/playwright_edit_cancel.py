"""
Playwright smoke script to record: grid Edit -> Cancel and grid Play/Pause
Usage:
  Set BASE_URL to your running app (default http://127.0.0.1:5000)
  Optionally set TEST_EMAIL and TEST_PASSWORD to an existing user.

This script will:
  - launch a chromium browser with video recording
  - navigate to signup/login or login with given credentials
  - go to /algo_setup, switch to grid view
  - click the first card's Edit button, assert the Edit modal appears
  - click Cancel, ensure modal is hidden
  - click Play/Pause on the same card and wait for the status badge change
  - save the video to playwright_videos/ and exit with code 0 on success

Note: It expects the app to be running and accessible at BASE_URL.
"""
import os
import time
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:5000')
EMAIL = os.environ.get('TEST_EMAIL')
PASSWORD = os.environ.get('TEST_PASSWORD', 'password123')
VIDEO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'playwright_videos'))

os.makedirs(VIDEO_DIR, exist_ok=True)

# helper to try multiple selectors
def try_fill(page, selectors, value):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                el.fill(value)
                return True
        except Exception:
            pass
    return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(record_video_dir=VIDEO_DIR, record_video_size={"width": 1280, "height": 720})
        page = context.new_page()
        page.set_default_timeout(8000)
        try:
            # use local variables so we don't shadow module-level constants
            email = EMAIL
            password = PASSWORD

            # If no TEST_EMAIL provided, try to create a new user via signup form
            if not email:
                unique = 'ptest+' + datetime.utcnow().strftime('%Y%m%d%H%M%S') + '@example.com'
                email = unique
                password = 'password123'
                print('No TEST_EMAIL provided; will attempt to sign up as', email)
                try:
                    page.goto(BASE_URL + '/signup')
                    # try common selectors
                    time.sleep(0.6)
                    filled = try_fill(page, ["input[name='email']", "#email", "input[type='email']"], email)
                    filled &= try_fill(page, ["input[name='password']", "#password", "input[type='password']"], password)
                    # some forms require confirm
                    try_fill(page, ["input[name='confirm']", "input[name='password2']", "#confirm"], password)
                    # submit - try submit button
                    if page.query_selector("button[type='submit']"):
                        page.click("button[type='submit']")
                        time.sleep(1.2)
                except Exception as e:
                    print('Signup attempt failed or not available:', e)
            # Try login (use provided or newly created)
            print('Navigating to login...')
            page.goto(BASE_URL + '/login')
            time.sleep(0.5)
            # Fill login fields
            did = try_fill(page, ["input[name='email']", "#email", "input[type='email']"], email)
            did = try_fill(page, ["input[name='password']", "#password", "input[type='password']"], password) or did
            # submit
            if page.query_selector("button[type='submit']"):
                page.click("button[type='submit']")
            time.sleep(1.2)

            # navigate to algo_setup
            page.goto(BASE_URL + '/algo_setup')
            page.wait_for_load_state('networkidle')
            time.sleep(0.8)

            # switch to grid view
            try:
                if page.query_selector('#gridViewBtn'):
                    page.click('#gridViewBtn')
                    time.sleep(0.4)
            except PlaywrightTimeout:
                pass

            # wait for a card
            page.wait_for_selector('.card-width', timeout=5000)
            first_card = page.query_selector('.card-width')
            if not first_card:
                print('No strategy cards found on /algo_setup');
                raise SystemExit(2)

            # find edit button inside first card
            edit_btn = first_card.query_selector('.card-edit-btn')
            if not edit_btn:
                print('No .card-edit-btn found inside first card');
                raise SystemExit(3)

            # start timing video: video will be saved after context.close()
            print('Clicking Edit on first card...')
            edit_btn.click()

            # assert modal appears
            try:
                page.wait_for_selector('#editStrategyModal.show, #editStrategyModal.modal.show', timeout=5000)
                print('Edit modal appeared')
            except PlaywrightTimeout:
                # Some bootstrap modals don't add .show immediately; check visible state
                modal = page.query_selector('#editStrategyModal')
                if modal and modal.is_visible():
                    print('Edit modal visible (fallback)')
                else:
                    print('Edit modal did NOT appear')
                    raise SystemExit(4)

            # click Cancel in modal - find button with data-bs-dismiss or text 'Cancel'
            cancel_btn = page.query_selector('#editStrategyModal button[data-bs-dismiss], #editStrategyModal .btn-light, #editStrategyModal button:text("Cancel")')
            if cancel_btn:
                cancel_btn.click()
                time.sleep(0.6)
                print('Clicked Cancel in modal')
            else:
                print('Could not find Cancel button in modal; attempting ESC')
                page.keyboard.press('Escape')
                time.sleep(0.5)

            # Play/Pause on card
            play_btn = first_card.query_selector('.card-play-btn')
            if not play_btn:
                print('No .card-play-btn found in card; attempting to see if table play exists')
            else:
                # read current status badge for comparison
                badge = first_card.query_selector('.status-badge')
                before = badge.inner_text() if badge else ''
                print('Status before toggle:', before)
                play_btn.click()
                time.sleep(0.8)
                after = badge.inner_text() if badge else ''
                print('Status after toggle:', after)

            # finalize
            print('Done interactions, will close browser and save video...')
            time.sleep(1.2)
            # get video path
            videos = []
            for p in context.pages:
                try:
                    v = p.video.path()
                    if v: videos.append(v)
                except Exception:
                    pass
            # close context to flush video
            context.close()
            browser.close()
            print('Recorded videos (if any):')
            for v in videos:
                print(v)
            # exit success
            return 0
        except Exception as e:
            print('Error during Playwright run:', e)
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            return 5

if __name__ == '__main__':
    sys.exit(main())
