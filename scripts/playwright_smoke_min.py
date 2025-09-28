import traceback
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
try:
    try:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto('http://127.0.0.1:5000/login', timeout=15000)
        print('url', page.url)
        page.screenshot(path='scripts/playwright_min.png', full_page=True)
        print('screenshot saved')
        ctx.close()
        browser.close()
    except Exception:
        traceback.print_exc()
        raise
finally:
    p.stop()
