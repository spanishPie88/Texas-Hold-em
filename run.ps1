$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path .).Path
$deps = Join-Path $projectRoot ".deps"
$env:PYTHONPATH = "$deps;$projectRoot"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
