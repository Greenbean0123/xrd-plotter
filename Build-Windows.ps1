$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m venv .build-venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
& .\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .\.build-venv\Scripts\python.exe build.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
