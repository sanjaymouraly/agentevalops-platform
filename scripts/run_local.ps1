$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install -r requirements.txt
Push-Location frontend; npm install; npm run build; Pop-Location
$env:PYTHONPATH = "backend"
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000
