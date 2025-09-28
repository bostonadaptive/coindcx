"""
Small Playwright diagnostic to check modal/bootstrap environment on /algo_setup
Prints simple diagnostics to stdout.
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get('BASE_URL', 'http://127.0.0.1:5000')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        page.goto(BASE + '/algo_setup', timeout=20000)
        try:
            page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:
            pass
        # diagnostics
        bs_present = page.evaluate('typeof window.bootstrap !== "undefined"')
        trigger_present = page.query_selector('#__openEditModalTrigger') is not None
        modal_present = page.query_selector('#editStrategyModal') is not None
        grid_visible = page.evaluate('''() => {
            const g = document.getElementById('resultsGridWrapper');
            if (!g) return false; const s = window.getComputedStyle(g); return s && s.display !== 'none' && g.offsetParent !== null;
        }''')
        cards_count = page.query_selector_all('.card-width').__len__()
        edit_buttons = page.query_selector_all('.card-edit-btn').__len__()

        print('finalUrl:', page.url)
        try:
            html = page.content()
            print('contentSnippet:', html[:2000].replace('\n',' '))
        except Exception:
            pass
        print('bootstrapPresent:', bs_present)
        print('triggerPresent:', trigger_present)
        print('modalPresent:', modal_present)
        print('gridVisible:', grid_visible)
        print('cardsCount:', cards_count)
        print('editButtons:', edit_buttons)
    except Exception as e:
        print('ERROR:', e)
    finally:
        try: ctx.close()
        except: pass
        try: browser.close()
        except: pass

