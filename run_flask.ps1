$proj = "D:\Backup\My Projects\CoinDCX\webApp"
$env:PYTHONPATH = $proj
$env:REDIS_URL = 'redis://127.0.0.1:6379'
$env:FLASK_APP = 'app'
Write-Output "Starting Flask with PYTHONPATH=$proj REDIS_URL=$env:REDIS_URL"
flask run --host=127.0.0.1
