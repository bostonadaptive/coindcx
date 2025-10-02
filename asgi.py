import os
import sys
import traceback
import logging
import functools
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from json.decoder import JSONDecodeError

# Import the existing app module (which still exposes the original Flask app
# and any converted FastAPI `router` objects). We mount the Flask app under
# `/legacy` so the site keeps running while we convert endpoints one-by-one.
import app as legacy_module

fastapi_app = FastAPI(title="CoinDCX (Hybrid) - FastAPI Frontend")
# Ensure a real secret in production; default is acceptable for local dev
session_secret = os.environ.get("SESSION_SECRET") or os.environ.get('SECRET_KEY') or "dev-secret"
fastapi_app.add_middleware(SessionMiddleware, secret_key=session_secret)

# Structured logger for adapters. Configure at module level; consumers can
# override handlers in production to integrate with their logging stack.
logger = logging.getLogger('asgi.adapters')
if not logger.handlers:
    # default to a simple console handler for local development
    h = logging.StreamHandler(sys.stderr)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    h.setFormatter(fmt)
    logger.addHandler(h)
logger.setLevel(os.environ.get('ASGI_ADAPTER_LOG_LEVEL', 'INFO'))


def log_exceptions(func):
    """Decorator for FastAPI adapter endpoints to log entry, exit and unhandled
    exceptions with contextual information (path, method, query params).
    Returns a JSONResponse on unhandled exceptions to keep behavior stable.
    """
    @functools.wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        path = None
        method = None
        q = None
        try:
            if hasattr(request, 'url'):
                path = getattr(request.url, 'path', None)
            method = getattr(request, 'method', None) if hasattr(request, 'method') else None
            q = dict(request.query_params) if hasattr(request, 'query_params') else None
        except Exception:
            # best-effort to collect context for logging
            path = path or None
            method = method or None
            q = q or None

        logger.info(f'adapter_call path={path} method={method} query={q}')

        try:
            res = await func(request, *args, **kwargs)
            logger.debug(f'adapter_success path={path} status={getattr(res, "status_code", None)}')
            return res
        except Exception as e:
            logger.exception('Unhandled exception in adapter', exc_info=True)
            return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)

    return wrapper


def _get_request_user_id(request: Request):
    """Return user_id from request in this order: query param 'user_id', header 'X-User-Id', session['user_id']"""
    try:
        # query param override (useful for tests)
        qp = getattr(request, 'query_params', {})
        if qp and qp.get('user_id'):
            try:
                return int(qp.get('user_id'))
            except Exception:
                return qp.get('user_id')
        # header override
        hdr = getattr(request, 'headers', None)
        if hdr and hdr.get('X-User-Id'):
            try:
                return int(hdr.get('X-User-Id'))
            except Exception:
                return hdr.get('X-User-Id')
        sess = getattr(request, 'session', {})
        if isinstance(sess, dict) and sess.get('user_id'):
            return sess.get('user_id')
    except Exception:
        pass
    return None

# Mount any converted FastAPI routers present in the module (best-effort)
try:
    if hasattr(legacy_module, 'router'):
        # mount converted router under /api to avoid colliding with legacy Flask paths
        fastapi_app.include_router(legacy_module.router, prefix="/api")
except Exception:
    # Ignore router mounting errors - best-effort include
    pass


# Provide a couple of small API adapters here to avoid editing the large legacy
# `app.py` while we continue incremental migration. These call into helper
# functions/variables present in the legacy module.

@log_exceptions
@fastapi_app.api_route('/api/ltp/batch', methods=['GET','POST'])
async def api_ltp_batch(request: Request):
    labels = []
    try:
        if request.method == 'POST':
            try:
                js = await request.json()
            except JSONDecodeError: # Explicitly catch JSON decoding failure
                js = {}
            except Exception: # Catch any other error during request.json()
                js = {}
            labels = js.get('labels') or []
        else:
            s = request.query_params.get('labels') or ''
            labels = [x.strip().upper() for x in s.split(',') if x.strip()]

        out = {}
        for lab in labels:
            if not lab:
                continue
            val = None
            try:
                # Check for LTP_CACHE existence and then try to get the value
                if lab in getattr(legacy_module, 'LTP_CACHE', {}):
                    v = legacy_module.LTP_CACHE.get(lab)
                    try:
                        # Explicitly catch ValueError/TypeError when converting to float
                        val = float(v if not isinstance(v, dict) else v.get('price'))
                    except (ValueError, TypeError):
                        val = None
            except AttributeError:
                # Catch if legacy_module has no LTP_CACHE or related issue
                val = None

            if val is None:
                try:
                    val = legacy_module.fetch_ltp_from_api(lab)
                except AttributeError:
                    # Catch if fetch_ltp_from_api is missing
                    val = None
                except Exception:
                    # Catch any other exception from fetch_ltp_from_api
                    val = None
            out[lab] = val
        return JSONResponse({'ltps': out})
    except Exception as e:
        # Final catch-all for the endpoint, returning a 500 error response
        return JSONResponse({'error': str(e)}, status_code=500)


@log_exceptions
@fastapi_app.post('/api/compute_qty')
async def api_compute_qty(request: Request):
    try:
        try:
            data = await request.json()
        except JSONDecodeError: # Explicitly catch JSON decoding failure
            data = {}
        except Exception: # Catch any other error during request.json()
            data = {}
            
        margin_inr = data.get('margin_inr') or data.get('margin')
        leverage = data.get('leverage') or data.get('lev') or 1
        symbol = data.get('symbol')
        price = data.get('price')
        usd_inr = data.get('usd_inr_rate') or data.get('usdinr')

        if (price in (None, '')) and symbol:
            try:
                pair = legacy_module.tv_to_pair_market(symbol)
                price = legacy_module.last_price_usdt(pair)
            except AttributeError:
                # Catch if legacy functions are missing
                price = None
            except Exception:
                price = None

        if usd_inr in (None, ''):
            try:
                from _tsl_logic import usdt_inr_fx
                usd_inr = usdt_inr_fx()
            except ImportError: # Explicitly catch if the module/function is missing
                usd_inr = None
            except Exception:
                usd_inr = None

        res = legacy_module.compute_qty_from_inr_margin(margin_inr, leverage, price, usd_inr)
        return JSONResponse(res)
    except Exception as e:
        # Log exception for debugging (better to use a proper logger)
        try:
            print('DEBUG: exception in api_compute_qty:', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        except Exception:
            pass
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Simple adapter: fetch instruments (wraps legacy `fetch_instruments` view logic which requires credentials)
@log_exceptions
@fastapi_app.get('/api/get_instruments')
async def api_get_instruments(request: Request):
    try:
        # The legacy view `fetch_instruments` requires a logged-in user with credentials in session.
        # We try to reuse the FastAPI session middleware to propagate the same session cookie.
        # If the legacy helper throws or credentials missing, return the same error dict the Flask view would.
        # Call the legacy helper directly where possible.
        if hasattr(legacy_module, 'get_active_instruments_tv'):
            instruments = legacy_module.get_active_instruments_tv()
            return JSONResponse(instruments)
        # Fallback: call the full view function if present (it returns a Flask jsonify response)
        if hasattr(legacy_module, 'fetch_instruments'):
            # call and coerce result
            resp = legacy_module.fetch_instruments()
            try:
                # If it's a Flask Response with get_json, attempt to extract JSON
                js = resp.get_json() if hasattr(resp, 'get_json') else resp
                return JSONResponse(js)
            except Exception:
                return JSONResponse({'error': 'failed_to_coerce_response'})
        return JSONResponse({'error': 'not_implemented'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


@log_exceptions
@fastapi_app.get('/api/ltp')
async def api_ltp(request: Request):
    try:
        label = request.query_params.get('label') if hasattr(request, 'query_params') else None
        if not label:
            return JSONResponse({'error': 'label required'}, status_code=400)
        try:
            v = legacy_module.fetch_ltp_from_api(label)
            return JSONResponse({'label': label, 'ltp': v})
        except Exception:
            # fallback to legacy view if present
            if hasattr(legacy_module, 'ltp_endpoint') and hasattr(legacy_module, 'app'):
                with legacy_module.app.test_request_context(query_string={'label': label}):
                    resp = legacy_module.ltp_endpoint()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'label': label, 'ltp': None}, status_code=500)
            return JSONResponse({'label': label, 'ltp': None}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


@log_exceptions
@fastapi_app.get('/api/strategy_signals')
async def api_strategy_signals_adapter(request: Request):
    try:
        # try calling the legacy api_strategy_signals view (which expects Flask request/session)
        if hasattr(legacy_module, 'api_strategy_signals') and hasattr(legacy_module, 'app'):
            with legacy_module.app.test_request_context(query_string=dict(request.query_params)):
                # copy session if available
                try:
                    from flask import session as _fsession
                    if isinstance(getattr(request, 'session', {}), dict) and request.session.get('user_id'):
                        _fsession['user_id'] = request.session.get('user_id')
                except Exception:
                    pass
                resp = legacy_module.api_strategy_signals()
            try:
                return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
            except Exception:
                return JSONResponse({'error': 'failed_to_coerce_response'}, status_code=500)
        return JSONResponse({'error': 'not_implemented'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


@log_exceptions
@fastapi_app.post('/api/refill_wallet')
async def api_refill_wallet(request: Request):
    try:
        uid = _get_request_user_id(request)
        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)

        # Try to reuse legacy helper if available
        if hasattr(legacy_module, 'refill_wallet') and hasattr(legacy_module, 'app'):
            with legacy_module.app.test_request_context():
                from flask import session as _fsession
                try:
                    _fsession['user_id'] = uid
                except Exception:
                    pass
                resp = legacy_module.refill_wallet()
            try:
                return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
            except Exception:
                return JSONResponse({'error': 'failed_to_coerce_response'}, status_code=500)

        # Fallback: perform DB update directly under app context
        if hasattr(legacy_module, 'app'):
            with legacy_module.app.app_context():
                try:
                    pw = legacy_module.PaperWallet.query.filter_by(user_id=uid).first()
                    if not pw:
                        pw = legacy_module.PaperWallet(user_id=uid, balance=100000, realized_pnl=0, unrealized_pnl=0, available_balance=100000)
                        legacy_module.db.session.add(pw)
                    pw.balance = 100000
                    pw.realized_pnl = 0
                    pw.unrealized_pnl = 0
                    pw.available_balance = 100000
                    legacy_module.db.session.commit()
                    return JSONResponse({
                        'success': True,
                        'balance': pw.balance,
                        'realized_pnl': getattr(pw, 'realized_pnl', None),
                        'unrealized_pnl': getattr(pw, 'unrealized_pnl', None),
                        'available_balance': getattr(pw, 'available_balance', None)
                    })
                except Exception:
                    try:
                        legacy_module.db.session.rollback()
                    except Exception:
                        pass
                    return JSONResponse({'error': 'internal'}, status_code=500)

        return JSONResponse({'error': 'not_implemented'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Adapter: get balance for current logged-in user
@log_exceptions
@fastapi_app.get('/api/get_balance')
async def api_get_balance(request: Request):
    try:
        # Attempt to access session-created credentials. The SessionMiddleware populates `request.session`.
        sess = getattr(request, 'session', {})
        user_id = sess.get('user_id') if isinstance(sess, dict) else None
        # If we can't find user_id, try legacy session (works when mounted under same cookie domain)
        if not user_id:
            # best-effort: try to call the legacy view which handles session internally
            if hasattr(legacy_module, 'get_balance'):
                if hasattr(legacy_module, 'app'):
                    with legacy_module.app.test_request_context():
                        resp = legacy_module.get_balance()
                else:
                    resp = legacy_module.get_balance()
                try:
                    # Catch failure to coerce Flask response
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'error': 'failed_to_coerce_response'})
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)

        # Fetch credentials from DB via legacy_module's models
        try:
            # Assuming legacy_module.Credentials.query is a SQLAlchemy query, which might raise various exceptions
            creds = legacy_module.Credentials.query.filter_by(user_id=user_id).first()
            if not creds:
                return JSONResponse({"connected": False, "error": "no_credentials"})
            result = legacy_module.get_balance_from_api(creds.api_key, creds.secret_key)
            return JSONResponse(result)
        except AttributeError:
            # fallback to calling legacy view
            if hasattr(legacy_module, 'get_balance'):
                if hasattr(legacy_module, 'app'):
                    with legacy_module.app.test_request_context():
                        resp = legacy_module.get_balance()
                else:
                    resp = legacy_module.get_balance()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'error': 'failed_to_coerce_response'})
            return JSONResponse({'error': 'internal'}, status_code=500)
        except Exception:
            # Catch general database/API call errors and fallback
            # fallback to calling legacy view
            if hasattr(legacy_module, 'get_balance'):
                resp = legacy_module.get_balance()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'error': 'failed_to_coerce_response'})
            return JSONResponse({'error': 'internal'}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)

# Adapter: get user's watchlist
@log_exceptions
@fastapi_app.get('/api/get_watchlist')
async def api_get_watchlist(request: Request):
    try:
        uid = _get_request_user_id(request)
        # Normal behavior: return empty watchlist for unauthenticated users
        # If uid not available, fall back to calling Flask view which uses session
        if not uid:
            # No authenticated user in session — return an empty watchlist for unauthenticated requests.
            return JSONResponse([], status_code=200)

        # Query DB via legacy models (needs Flask app context)
        try:
            if hasattr(legacy_module, 'app'):
                with legacy_module.app.app_context():
                    wl = legacy_module.Watchlist.query.filter_by(user_id=uid).all()
            else:
                wl = legacy_module.Watchlist.query.filter_by(user_id=uid).all()
            out = []
            for w in wl:
                tv, label = legacy_module.parse_to_tv_symbol(w.symbol)
                ltp = legacy_module.fetch_ltp_from_api(label)
                out.append({"symbol": tv, "label": label, "ltp": ltp})
            return JSONResponse(out)
        except AttributeError:
            # Catch if legacy_module.Watchlist or helper functions are missing
            # fallback to view
            if hasattr(legacy_module, 'get_watchlist'):
                # Call legacy view inside Flask test_request_context to provide
                # request/session context for the view when running in-process.
                if hasattr(legacy_module, 'app'):
                    with legacy_module.app.test_request_context():
                        resp = legacy_module.get_watchlist()
                else:
                    resp = legacy_module.get_watchlist()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'error': 'failed_to_coerce_response'})
            return JSONResponse({'error': 'internal'}, status_code=500)
        except Exception:
            # Catch general database/API call errors
            # fallback to view
            if hasattr(legacy_module, 'get_watchlist'):
                resp = legacy_module.get_watchlist()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'error': 'failed_to_coerce_response'})
            return JSONResponse({'error': 'internal'}, status_code=500)

    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)

# Adapter: get current user's paper wallet
@log_exceptions
@fastapi_app.get('/api/get_paper_wallet')
async def api_get_paper_wallet(request: Request):
    try:
        uid = _get_request_user_id(request)
        # Normal behavior

        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)

        try:
            if hasattr(legacy_module, 'app'):
                with legacy_module.app.app_context():
                    pw = legacy_module.PaperWallet.query.filter_by(user_id=uid).first()
            else:
                pw = legacy_module.PaperWallet.query.filter_by(user_id=uid).first()
            if not pw:
                return JSONResponse({"error": "No paper wallet found."}, status_code=404)
            return JSONResponse({
                "balance": pw.balance,
                "realized_pnl": getattr(pw, 'realized_pnl', None),
                "unrealized_pnl": getattr(pw, 'unrealized_pnl', None),
                "available_balance": getattr(pw, 'available_balance', None),
            })
        except Exception:
            # Fallback: attempt to call legacy view within Flask context
            if hasattr(legacy_module, 'get_paper_wallet') and hasattr(legacy_module, 'app'):
                with legacy_module.app.test_request_context():
                    resp = legacy_module.get_paper_wallet()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'error': 'failed_to_coerce_response'})
            return JSONResponse({'error': 'internal'}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Adapter: get positions (wraps legacy get_positions view/helper)
@log_exceptions
@fastapi_app.get('/api/get_positions')
async def api_get_positions(request: Request):
    try:
        uid = _get_request_user_id(request)
        # Normal behavior
        if not uid:
            # Unauthenticated — return empty positions list.
            return JSONResponse([], status_code=200)

        if not hasattr(legacy_module, 'get_positions'):
            return JSONResponse({'error': 'get_positions_not_found'}, status_code=404)
        
        try:
            if hasattr(legacy_module, 'app'):
                with legacy_module.app.test_request_context():
                    resp = legacy_module.get_positions()
            else:
                resp = legacy_module.get_positions()
            # `get_positions` returns a Flask response; attempt to coerce
            try:
                # Catch failure to coerce Flask response
                return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
            except Exception as e:
                print(f"DEBUG: failed to coerce get_positions response: {e}", file=sys.stderr)
                return JSONResponse({'error': 'failed_to_coerce_response'})
        except Exception:
            # Catch general exception from calling legacy_module.get_positions()
            return JSONResponse({'error': 'internal'}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Mount the legacy Flask app under /legacy so it remains available until fully migrated.
try:
    if hasattr(legacy_module, 'app'):
        fastapi_app.mount('/legacy', WSGIMiddleware(legacy_module.app))
except Exception:
    pass

# Expose a small health endpoint
@fastapi_app.get('/health')
async def health():
    return {"status": "ok"}


# ...existing code for adapters...


# Adapter: check broker connection status (wraps existing get_balance/check_broker_status helpers)
@log_exceptions
@fastapi_app.get('/api/check_broker_status')
async def api_check_broker_status(request: Request):
    try:
        uid = _get_request_user_id(request)
        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)

        try:
            if hasattr(legacy_module, 'app'):
                with legacy_module.app.app_context():
                    creds = legacy_module.Credentials.query.filter_by(user_id=uid).first()
            else:
                creds = legacy_module.Credentials.query.filter_by(user_id=uid).first()
            if not creds:
                return JSONResponse({'connected': False, 'error': 'no_credentials'})
            # use existing helper if present
            try:
                res = legacy_module.get_balance_from_api(creds.api_key, creds.secret_key)
                return JSONResponse(res)
            except Exception:
                # fallback to calling legacy view inside Flask context
                if hasattr(legacy_module, 'check_broker_status') and hasattr(legacy_module, 'app'):
                    with legacy_module.app.test_request_context():
                        resp = legacy_module.check_broker_status()
                    try:
                        return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                    except Exception:
                        return JSONResponse({'connected': False})
                return JSONResponse({'connected': False})
        except Exception:
            return JSONResponse({'connected': False}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Adapter: fetch real account data (balance,PnL) for logged-in user
@log_exceptions
@fastapi_app.get('/api/get_real_account_data')
async def api_get_real_account_data(request: Request):
    try:
        uid = _get_request_user_id(request)
        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)

        try:
            # Query credentials under Flask app context if available
            if hasattr(legacy_module, 'app'):
                with legacy_module.app.app_context():
                    creds = legacy_module.Credentials.query.filter_by(user_id=uid).first()
            else:
                creds = legacy_module.Credentials.query.filter_by(user_id=uid).first()

            if creds:
                try:
                    broker_data = legacy_module.get_balance_from_api(creds.api_key, creds.secret_key)
                except Exception:
                    broker_data = {}
                return JSONResponse({
                    'success': True,
                    'balance': broker_data.get('balance'),
                    'realized_pnl': broker_data.get('realized'),
                    'unrealized_pnl': broker_data.get('unrealized'),
                    'available_balance': broker_data.get('available')
                })

            return JSONResponse({'success': False}, status_code=404)
        except Exception:
            # fallback to legacy view inside Flask context
            if hasattr(legacy_module, 'get_real_account_data') and hasattr(legacy_module, 'app'):
                # Ensure Flask request.session has the user_id so legacy view doesn't KeyError
                from flask import session as _flask_session
                with legacy_module.app.test_request_context():
                    try:
                        _flask_session['user_id'] = uid
                    except Exception:
                        # In some Flask setups session may not be writable; ignore and proceed
                        pass
                    resp = legacy_module.get_real_account_data()
                try:
                    return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
                except Exception:
                    return JSONResponse({'success': False}, status_code=500)
            return JSONResponse({'success': False}, status_code=500)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Test helper: set session for TestClient (enabled only when ASGI_ENABLE_TEST_HELPERS=1)
if os.environ.get('ASGI_ENABLE_TEST_HELPERS') == '1':
    @fastapi_app.post('/api/_set_session')
    async def _set_session(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        uid = data.get('user_id')
        if uid is None:
            return JSONResponse({'error': 'user_id required'}, status_code=400)
        try:
            # starlette SessionMiddleware exposes request.session as a dict
            request.session['user_id'] = uid
        except Exception:
            return JSONResponse({'error': 'session_fail'}, status_code=500)
        return JSONResponse({'ok': True})


# Adapter: add to watchlist
@log_exceptions
@fastapi_app.post('/api/add_watchlist')
async def api_add_watchlist(request: Request):
    try:
        sess = getattr(request, 'session', {})
        uid = sess.get('user_id') if isinstance(sess, dict) else None
        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)
        try:
            data = await request.json()
        except Exception:
            data = {}
        symbol = data.get('symbol')
        if not symbol:
            return JSONResponse({'error': 'symbol required'}, status_code=400)

        # Prefer direct DB update under Flask app context
        if hasattr(legacy_module, 'app'):
            with legacy_module.app.app_context():
                try:
                    tv, label = legacy_module.parse_to_tv_symbol(symbol)
                    if not legacy_module.Watchlist.query.filter_by(user_id=uid, symbol=tv).first():
                        legacy_module.db.session.add(legacy_module.Watchlist(user_id=uid, symbol=tv))
                        legacy_module.db.session.commit()
                    return JSONResponse({'message': 'Added', 'symbol': tv, 'label': label})
                except Exception:
                    try:
                        legacy_module.db.session.rollback()
                    except Exception:
                        pass
                    return JSONResponse({'error': 'internal'}, status_code=500)

        # Fallback: try calling legacy view inside Flask test_request_context
        if hasattr(legacy_module, 'add_watchlist') and hasattr(legacy_module, 'app'):
            with legacy_module.app.test_request_context(json={'symbol': symbol}):
                resp = legacy_module.add_watchlist()
            try:
                return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
            except Exception:
                return JSONResponse({'error': 'failed_to_coerce_response'}, status_code=500)

        return JSONResponse({'error': 'not_implemented'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Adapter: remove from watchlist
@log_exceptions
@fastapi_app.post('/api/remove_watchlist')
async def api_remove_watchlist(request: Request):
    try:
        sess = getattr(request, 'session', {})
        uid = sess.get('user_id') if isinstance(sess, dict) else None
        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)
        try:
            data = await request.json()
        except Exception:
            data = {}
        symbol = data.get('symbol')
        if not symbol:
            return JSONResponse({'error': 'symbol required'}, status_code=400)

        if hasattr(legacy_module, 'app'):
            with legacy_module.app.app_context():
                try:
                    item = legacy_module.Watchlist.query.filter_by(user_id=uid, symbol=symbol).first()
                    if item:
                        legacy_module.db.session.delete(item)
                        legacy_module.db.session.commit()
                    return JSONResponse({'message': 'Removed'})
                except Exception:
                    try:
                        legacy_module.db.session.rollback()
                    except Exception:
                        pass
                    return JSONResponse({'error': 'internal'}, status_code=500)

        if hasattr(legacy_module, 'remove_watchlist') and hasattr(legacy_module, 'app'):
            with legacy_module.app.test_request_context(json={'symbol': symbol}):
                resp = legacy_module.remove_watchlist()
            try:
                return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
            except Exception:
                return JSONResponse({'error': 'failed_to_coerce_response'}, status_code=500)

        return JSONResponse({'error': 'not_implemented'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)


# Adapter: update api key/secret (partial of update_api_key)
@log_exceptions
@fastapi_app.post('/api/update_api_key')
async def api_update_api_key(request: Request):
    try:
        sess = getattr(request, 'session', {})
        uid = sess.get('user_id') if isinstance(sess, dict) else None
        if not uid:
            return JSONResponse({'error': 'not_authenticated'}, status_code=401)
        try:
            data = await request.json()
        except Exception:
            data = {}
        field = data.get('field')
        value = data.get('value')
        if field not in ('apiKey', 'secretKey'):
            return JSONResponse({'error': 'invalid_field'}, status_code=400)

        if hasattr(legacy_module, 'app'):
            with legacy_module.app.app_context():
                try:
                    creds = legacy_module.Credentials.query.filter_by(user_id=uid).first()
                    if not creds:
                        creds = legacy_module.Credentials(user_id=uid)
                        legacy_module.db.session.add(creds)
                    if field == 'apiKey':
                        creds.api_key = value
                    else:
                        creds.secret_key = value
                    legacy_module.db.session.commit()
                    return JSONResponse({'success': True})
                except Exception:
                    try:
                        legacy_module.db.session.rollback()
                    except Exception:
                        pass
                    return JSONResponse({'error': 'internal'}, status_code=500)

        # Fallback: call legacy view if available
        if hasattr(legacy_module, 'update_api_key') and hasattr(legacy_module, 'app'):
            with legacy_module.app.test_request_context(json={'field': field, 'value': value}):
                resp = legacy_module.update_api_key()
            try:
                return JSONResponse(resp.get_json() if hasattr(resp, 'get_json') else resp)
            except Exception:
                return JSONResponse({'error': 'failed_to_coerce_response'}, status_code=500)

        return JSONResponse({'error': 'not_implemented'}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': 'internal', 'msg': str(e)}, status_code=500)

if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    # Note: 'asgi:fastapi_app' assumes this file is named 'asgi.py'. If your file is different, adjust this string.
    uvicorn.run('asgi:fastapi_app', host='0.0.0.0', port=port, reload=True)