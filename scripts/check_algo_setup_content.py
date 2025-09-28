"""
Login with given credentials and print /algo_setup HTML snippet and element presence flags.
"""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get('BASE_URL', 'http://127.0.0.1:5000')
EMAIL = os.environ.get('TEST_EMAIL') or 'ptest+20250926203406@example.com'
PASSWORD = os.environ.get('TEST_PASSWORD') or 'password123'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        page.goto(BASE + '/login')
        page.fill("input[name='email']", EMAIL)
        page.fill("input[name='password']", PASSWORD)
        if page.query_selector("button[type='submit']"):
            page.click("button[type='submit']")
        page.wait_for_load_state('networkidle', timeout=10000)
        page.goto(BASE + '/algo_setup')
        page.wait_for_load_state('networkidle', timeout=10000)
        html = page.content()
        has_bs = page.evaluate('typeof window.bootstrap !== "undefined"')
        has_trigger = page.query_selector('#__openEditModalTrigger') is not None
        has_modal = page.query_selector('#editStrategyModal') is not None
        cards = len(page.query_selector_all('.card-width'))
        edits = len(page.query_selector_all('.card-edit-btn'))
        print('url=', page.url)
        print('bootstrap=', has_bs)
        print('__openEditModalTrigger=', has_trigger)
        print('editStrategyModal=', has_modal)
        print('cards=', cards, 'editButtons=', edits)
        # print small snippet around modal if present
        if has_modal:
            idx = html.find('<div class="modal fade" id="editStrategyModal"')
            print('modalSnippet:', html[idx:idx+800])
        else:
            print('modal not found in HTML')
    except Exception as e:
        print('ERROR', e)
    finally:
        try: ctx.close()
        except: pass
        try: browser.close()
        except: pass
