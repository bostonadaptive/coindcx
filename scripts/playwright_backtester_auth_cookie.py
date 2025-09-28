import requests
from playwright.sync_api import sync_playwright
import os

BASE = 'http://127.0.0.1:5000'
TEST_EMAIL = os.environ.get('TEST_EMAIL', 'test@example.com')
TEST_PASSWORD = os.environ.get('TEST_PASSWORD', 'password123')

# Use requests to login and extract Flask session cookie
with requests.Session() as s:
    # perform login POST
    r = s.post(BASE + '/login', data={'email': TEST_EMAIL, 'password': TEST_PASSWORD}, allow_redirects=True, timeout=10)
    if r.status_code >= 400:
        print('Login POST failed, status', r.status_code)
    # Extract cookies
    cookies = s.cookies.get_dict()
    print('requests cookies:', cookies)

    # Start Playwright and inject cookies
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Translate cookies into Playwright format and add to context
        pw_cookies = []
        for name, value in cookies.items():
            pw_cookies.append({'name': name, 'value': value, 'domain': '127.0.0.1', 'path': '/'} )
        if pw_cookies:
            context.add_cookies(pw_cookies)

        page = context.new_page()
        page.goto(BASE + '/backtester', timeout=15000)
        page.wait_for_load_state('networkidle')

        # Wait for window.allSymbols to populate
        for _ in range(20):
            all_len = page.evaluate('window.allSymbols ? window.allSymbols.length : 0')
            if all_len and all_len > 0:
                print('allSymbols loaded:', all_len)
                break
            page.wait_for_timeout(500)
        else:
            print('Timed out waiting for allSymbols to load')

        try:
            page.wait_for_selector('#symbolSearchInput', timeout=5000)
            page.fill('#symbolSearchInput', 'btc')
            page.wait_for_timeout(500)
            count = page.evaluate("() => document.querySelectorAll('#symbolSuggestions li').length")
            print('suggestions count:', count)
        except Exception as e:
            print('Error checking suggestions:', e)

        context.close()
        browser.close()
