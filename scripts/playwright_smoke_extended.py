import os
import traceback
from playwright.sync_api import sync_playwright

TEST_EMAIL = os.environ.get('TEST_EMAIL', 'test@example.com')
TEST_PASSWORD = os.environ.get('TEST_PASSWORD', 'password123')

pages = [
    ('/login', 'playwright_login.png'),
    ('/algo_setup', 'playwright_algo_setup.png'),
    ('/algo_trading', 'playwright_algo_trading.png'),
    ('/backtester', 'playwright_backtester.png'),
]

p = sync_playwright().start()
try:
    try:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Go to login page and attempt to log in
        page.goto('http://127.0.0.1:5000/login', timeout=15000)
        # try to fill login form
        try:
            page.fill("input[name='email']", TEST_EMAIL)
            page.fill("input[name='password']", TEST_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            # If form not present or login fails, continue to capture pages as anonymous
            pass

        for route, fname in pages:
            try:
                page.goto('http://127.0.0.1:5000' + route, timeout=15000)
                page.wait_for_load_state('networkidle', timeout=8000)
                page.screenshot(path=os.path.join('scripts', fname), full_page=True)
                print('captured', route, '->', fname)
            except Exception:
                traceback.print_exc()
                print('failed to capture', route)

        ctx.close()
        browser.close()
    except Exception:
        traceback.print_exc()
        raise
finally:
    p.stop()
