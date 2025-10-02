# coindcx

## Migration notes (FastAPI frontend)

This repository is in a hybrid migration state: the original Flask app remains mounted under `/legacy`, while a FastAPI frontend exposes new and adapter endpoints under `/api`.

Key points:
- The FastAPI app is defined in `asgi.py` and mounts the legacy Flask `app` with WSGIMiddleware at `/legacy`.
- During migration we've added "native" endpoints (suffixed with `_native`) that call the existing SQLAlchemy models and helpers under `legacy_module.app.app_context()` to avoid touching the large `app.py` surface area.
- Adapters remain for many endpoints and will be removed or replaced once clients switch to the native endpoints.

Testing and test helpers
- Tests use `pytest` and FastAPI `TestClient`.
- For test convenience a small helper endpoint `/api/_set_session` is available when `ASGI_ENABLE_TEST_HELPERS=1`. Many tests also pass `user_id` as a query param to override authentication in-process.
- To run tests locally:

```powershell
cd "D:\Backup\My Projects\CoinDCX\webApp"
pytest -q
```

What was migrated in this pass
- Native endpoints added: `/api/get_balance_native`, `/api/get_watchlist_native`, `/api/get_positions_native`, `/api/refill_wallet_native`, `/api/profile_native`, `/api/strategy_signals` (adapter retained with session-copy), `/api/check_broker_status_native`, `/api/get_real_account_data_native`, and several small POST handlers `/api/add_watchlist_native`, `/api/remove_watchlist_native`, `/api/update_api_key_native`.
- Tests covering the above endpoints were added/updated.

Follow-ups / TODOs
- Update CI workflow to set `ASGI_ENABLE_TEST_HELPERS=1` for the test run or update tests to set session via the helper.
- Review CSRF and auth flows before promoting native endpoints to production — native POST endpoints currently accept session overrides for tests and rely on the Flask DB models; ensure proper auth in client-facing deployments.
- Plan to deprecate adapter endpoints and remove `/legacy` mount once all clients are migrated.

If you'd like I can commit these changes, push the feature branch, and open a PR with this summary.
