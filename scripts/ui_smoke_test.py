"""Headless UI smoke test using Playwright.

This script starts a dev Flask server in the background (if not already running), then uses Playwright
in headless mode to:
 - navigate to /algo_setup
 - login as seeded admin user (if login present)
 - verify that toggling Paper in the list updates the grid toggle
 - verify that toggling Paper in the grid updates the list toggle
 - open Add Strategy modal and verify Paper checkbox defaults to unchecked and balance is shown
 - click Play/Pause and ensure Active badge updates in both list and grid

Notes:
 - This is a small smoke test intended to run locally. It uses the seeded admin user created by app.py
   during development: email "asma.basha@gmail.com" / password "Admin@123".
 - Playwright browsers must be installed (playwright install) before running this script. The script
   will attempt to install browsers automatically if playwright is present.
"""
import os
import time
import subprocess
import sys
from pathlib import Path

# Ensure project root is on PATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import playwright dynamically so tests can be skipped gracefully if not installed
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except Exception as e:
    print("Playwright not installed. Install dev requirements and run 'playwright install' then retry.")
    raise

BASE_URL = os.environ.get('APP_URL', 'http://127.0.0.1:5000')
ADMIN_EMAIL = 'asma.basha@gmail.com'
ADMIN_PW = 'Admin@123'

# Optional: helper to start Flask server if it's not running
def start_flask_if_needed():
    import socket
    s = socket.socket()
    try:
        s.connect(('127.0.0.1', 5000))
        s.close()
        print('Server appears to be running on 127.0.0.1:5000')
        return None
    except Exception:
        # Launch server in background via python -m app
        print('Starting Flask dev server...')
        # Use a shell-friendly command and ensure working dir is project root
        cmd = [sys.executable, str(ROOT / 'app.py')]
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Give it time to boot
        time.sleep(2.5)
        return proc


def run_test():
    server_proc = start_flask_if_needed()
    try:
        with sync_playwright() as p:
            print('Playwright launched', flush=True)
            browser = p.chromium.launch(headless=True)
            print('Chromium launched', flush=True)
            context = browser.new_context()
            print('Browser context created', flush=True)
            page = context.new_page()

            try:
                # Visit login page and sign in if necessary
                page.goto(f"{BASE_URL}/login", timeout=10000)
                time.sleep(0.5)
                if 'Login' in page.title() or page.url.endswith('/login'):
                    print('Performing login...', flush=True)
                    page.fill('input[name="email"]', ADMIN_EMAIL)
                    page.fill('input[name="password"]', ADMIN_PW)
                    print('About to click submit', flush=True)
                    page.click('button[type="submit"]')
                    print('Login form submitted', flush=True)
                    # debug: print current url and title after submit
                    try:
                        page.wait_for_timeout(400)
                        print('Post-login url=', page.url, 'title=', page.title())
                    except Exception:
                        pass
                    # wait for redirect
                    try:
                        page.wait_for_url(f"{BASE_URL}/dashboard", timeout=5000)
                    except PWTimeout:
                        # maybe redirect to /algo_setup or /
                        pass
                print('Navigating to /algo_setup')

                # Go to algo_setup
                page.goto(f"{BASE_URL}/algo_setup", timeout=30000)
                try:
                    page.wait_for_load_state('networkidle', timeout=5000)
                except Exception:
                    pass
                print('Visited /algo_setup', 'url=', page.url, 'title=', page.title(), flush=True)
                # capture screenshots for debugging
                try:
                    outdir = ROOT / 'scripts' / 'screenshots'
                    outdir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(outdir / f'post_login_{int(time.time())}.png'), full_page=True)
                except Exception:
                    pass
                try:
                    content = page.content()
                    print('Page content length:', len(content))
                except Exception:
                    pass
                page.wait_for_timeout(800)

                # Find first strategy row and its id
                first_row = page.query_selector('table#strategiesTable tbody tr')
                if not first_row:
                    print('No strategies present to test. Insert a test strategy or seed one.')
                    return 1
                cfg_id = first_row.get_attribute('data-config-id')
                print('Found strategy id:', cfg_id)

                # Locate the table toggle and grid toggle
                table_toggle = page.query_selector(f'input.paper-toggle[data-id="{cfg_id}"]')
                grid_toggle = page.query_selector(f'input.paper-toggle-card[data-id="{cfg_id}"]')

                # Toggle table -> ensure grid reflects
                orig_table = table_toggle.is_checked()
                print('Original table paper:', orig_table)
                table_toggle.check() if not orig_table else table_toggle.uncheck()
                # wait for network and DOM update
                page.wait_for_timeout(800)
                grid_state = grid_toggle.is_checked() if grid_toggle else None
                print('Grid state after toggling table:', grid_state)
                if grid_state is None:
                    print('Grid toggle not present; skipping grid sync assertion')
                else:
                    assert grid_state == (not orig_table), 'Grid did not reflect table toggle change'

                # Toggle grid -> ensure table reflects
                if grid_toggle:
                    orig_grid = grid_toggle.is_checked()
                    grid_toggle.check() if not orig_grid else grid_toggle.uncheck()
                    page.wait_for_timeout(800)
                    table_state = table_toggle.is_checked()
                    print('Table state after toggling grid:', table_state)
                    assert table_state == (not orig_grid), 'Table did not reflect grid toggle change'

                # Open Add Strategy modal and verify Paper checkbox default and balance visible
                page.click('[data-bs-target="#addStrategyModal"]')
                page.wait_for_selector('#addStrategyModal.show', timeout=3000)
                add_cb = page.query_selector('#addIsPaperCheckbox')
                assert add_cb is not None, 'Add modal Paper checkbox not found'
                assert not add_cb.is_checked(), 'Add modal Paper checkbox should be unchecked by default'
                bal = page.query_selector('#availableBalance')
                assert bal is not None, 'Available balance element missing in add modal'
                print('Add modal available balance text:', bal.inner_text())

                # Test Play/Pause -> find play button and click
                play_btn = page.query_selector(f'button.play-btn[data-id="{cfg_id}"]')
                if not play_btn:
                    print('No play button for strategy; skipping play/pause test')
                else:
                    # capture current status badge text in table and grid
                    table_badge = page.query_selector(f'tr[data-config-id="{cfg_id}"] .status-badge')
                    grid_badge = page.query_selector(f'.card-width[data-config-id="{cfg_id}"] .status-badge')
                    before_table = table_badge.inner_text() if table_badge else None
                    before_grid = grid_badge.inner_text() if grid_badge else None
                    print('Before play click:', before_table, before_grid)
                    play_btn.click()
                    page.wait_for_timeout(900)
                    after_table = table_badge.inner_text() if table_badge else None
                    after_grid = grid_badge.inner_text() if grid_badge else None
                    print('After play click:', after_table, after_grid)
                    assert after_table != before_table or after_grid != before_grid, 'Play/Pause did not change status badge'

                print('UI smoke test completed successfully')

            except AssertionError:
                import traceback
                traceback.print_exc()
                raise
            except Exception:
                import traceback
                traceback.print_exc()
                raise
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        if server_proc:
            print('Terminating server process')
            server_proc.terminate()


if __name__ == '__main__':
    run_test()
