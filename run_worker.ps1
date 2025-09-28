$proj = "D:\Backup\My Projects\CoinDCX\webApp"
$env:PYTHONPATH = $proj
$env:REDIS_URL = 'redis://127.0.0.1:6379'
Write-Output "Starting signals_worker with PYTHONPATH=$proj REDIS_URL=$env:REDIS_URL"
python -c "import sys; sys.path.insert(0, r'$proj'); import workers.signals_worker as w; w.run_worker_loop()"
