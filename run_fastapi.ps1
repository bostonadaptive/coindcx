$env:SESSION_SECRET = "dev-secret"
# Windows PowerShell runner for uvicorn
python -m uvicorn asgi:fastapi_app --host 127.0.0.1 --port 8000
