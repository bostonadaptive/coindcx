from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    # Try to login first (if TEST_EMAIL/TEST_PASSWORD env vars are provided)
    import os
    TEST_EMAIL = os.environ.get('TEST_EMAIL')
    TEST_PASSWORD = os.environ.get('TEST_PASSWORD')
    if TEST_EMAIL and TEST_PASSWORD:
        page.goto('http://127.0.0.1:5000/login', timeout=15000)
        try:
            page.fill("input[name='email']", TEST_EMAIL)
            page.fill("input[name='password']", TEST_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass

    page.goto('http://127.0.0.1:5000/algo_setup', timeout=15000)
    page.wait_for_load_state('networkidle', timeout=8000)

    # Open Add modal
    try:
        page.click('[data-bs-target="#addStrategyModal"]')
    except Exception:
        pass
    page.wait_for_selector('#symbolSearchInputAdd')
    page.fill('#symbolSearchInputAdd', 'btc')
    page.wait_for_timeout(500)
    add_count = page.evaluate("() => document.querySelectorAll('#symbolSuggestionsAdd li').length")
    print('Add suggestions count:', add_count)

    # Try Edit: if there is an edit button, click the first one to open modal
    try:
        page.click('.card-edit-btn')
    except Exception:
        pass
    page.wait_for_timeout(500)
    # Fill edit input if present
    try:
        page.fill('#editSymbolInput', 'btc')
        page.wait_for_timeout(500)
        edit_count = page.evaluate("() => document.querySelectorAll('#symbolSuggestionsEdit li').length")
    except Exception:
        edit_count = 'no-edit-input'
    print('Edit suggestions count:', edit_count)

    ctx.close()
    browser.close()
