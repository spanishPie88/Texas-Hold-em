@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%.deps;%ROOT%"
cd /d "%ROOT%"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
endlocal

