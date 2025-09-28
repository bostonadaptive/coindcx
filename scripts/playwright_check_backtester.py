from playwright.sync_api import sync_playwright
import os

TEST_EMAIL = os.environ.get('TEST_EMAIL', 'test@example.com')
TEST_PASSWORD = os.environ.get('TEST_PASSWORD', 'password123')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()

    # Login first to ensure we reach backtester as an authenticated user
    page.goto('http://127.0.0.1:5000/login', timeout=15000)
    try:
        page.fill('input[name="email"]', TEST_EMAIL)
        page.fill('input[name="password"]', TEST_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle', timeout=8000)
    except Exception:
        pass

    page.goto('http://127.0.0.1:5000/backtester', timeout=15000)
    page.wait_for_load_state('networkidle', timeout=8000)

    # wait for instruments to populate window.allSymbols (timeout after 10s)
    for _ in range(20):
        all_len = page.evaluate('window.allSymbols ? window.allSymbols.length : 0')
        if all_len and all_len > 0:
            print('allSymbols loaded:', all_len)
            break
        page.wait_for_timeout(500)
    else:
        print('Timed out waiting for allSymbols to load')

    # ensure input present
    try:
        page.wait_for_selector('#symbolSearchInput', timeout=5000)
        page.fill('#symbolSearchInput', 'btc')
        page.wait_for_timeout(500)
        count = page.evaluate("() => document.querySelectorAll('#symbolSuggestions li').length")
        print('suggestions count:', count)
    except Exception as e:
        print('Error checking suggestions:', e)

    ctx.close()
    browser.close()
