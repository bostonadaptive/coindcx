"""
Headless Playwright test to assert Edit modal opens when grid edit clicked.
Exits 0 on success, non-zero on failure.
"""
import os, sys, time
from playwright.sync_api import sync_playwright, TimeoutError

import argparse

BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:5000')
ENV_EMAIL = os.environ.get('TEST_EMAIL')
ENV_PASSWORD = os.environ.get('TEST_PASSWORD', 'password123')

parser = argparse.ArgumentParser()
parser.add_argument('--email', help='Test user email', default=None)
parser.add_argument('--password', help='Test user password', default=None)
args = parser.parse_args()

EMAIL = args.email if args.email else ENV_EMAIL
PASSWORD = args.password if args.password else ENV_PASSWORD


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


def run_test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        # increase default timeout to reduce flakiness on slow CI or dev machines
        page.set_default_timeout(15000)
        try:
            # login flow
            # login or sign up if no TEST_EMAIL
            email = EMAIL
            password = PASSWORD
            if not email:
                # attempt signup flow to create a test user
                unique = 'ptest+' + __import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S') + '@example.com'
                email = unique
                password = 'password123'
                try:
                    page.goto(BASE_URL + '/signup')
                    time.sleep(0.4)
                    try_fill(page, ["input[name='email']", "#email", "input[type='email']"], email)
                    try_fill(page, ["input[name='password']", "#password", "input[type='password']"], password)
                    try_fill(page, ["input[name='confirm']", "input[name='password2']", "#confirm"], password)
                    if page.query_selector("button[type='submit']"):
                        page.click("button[type='submit']")
                        time.sleep(0.8)
                except Exception as e:
                    print('Signup attempt failed:', e)
            # now attempt login
            page.goto(BASE_URL + '/login')
            time.sleep(0.3)
            try_fill(page, ["input[name='email']", "#email", "input[type='email']"], email)
            try_fill(page, ["input[name='password']", "#password", "input[type='password']"], password)
            if page.query_selector("button[type='submit']"):
                page.click("button[type='submit']")
            time.sleep(0.8)
            page.goto(BASE_URL + '/algo_setup')
            # wait for network idle so dynamic JS can render the grid/list
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                # best-effort; continue
                pass

            # Ensure grid view is active: if resultsGridWrapper not visible, click the grid toggle
            try:
                if not page.is_visible('#resultsGridWrapper'):
                    if page.query_selector('#gridViewBtn'):
                        page.click('#gridViewBtn')
                    # wait for the grid wrapper to become visible
                    page.wait_for_selector('#resultsGridWrapper', state='visible', timeout=8000)

                # now wait for at least one visible card element
                page.wait_for_selector('.card-width', state='visible', timeout=15000)
            except TimeoutError:
                # fallback attempt: try clicking the grid toggle and wait a bit more
                try:
                    if page.query_selector('#gridViewBtn'):
                        page.click('#gridViewBtn')
                        page.wait_for_timeout(500)
                    page.wait_for_selector('.card-width', state='visible', timeout=10000)
                except Exception:
                    # re-raise to be caught by outer handler
                    raise
            first_card = page.query_selector('.card-width')
            if not first_card:
                print('No card found')
                return 3
            edit_btn = first_card.query_selector('.card-edit-btn')
            if not edit_btn:
                print('No edit button found in card')
                return 4
            edit_btn.click()
            try:
                page.wait_for_selector('#editStrategyModal.show, #editStrategyModal.modal.show', timeout=3000)
                print('Modal shown OK')
                context.close()
                browser.close()
                return 0
            except TimeoutError:
                modal = page.query_selector('#editStrategyModal')
                if modal and modal.is_visible():
                    print('Modal visible (fallback)')
                    context.close()
                    browser.close()
                    return 0
                print('Modal did NOT appear')
                context.close()
                browser.close()
                return 5
        except Exception as e:
            print('Test run exception', e)
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            return 6

if __name__ == '__main__':
    sys.exit(run_test())
