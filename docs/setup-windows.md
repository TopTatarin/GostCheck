# Setup — Windows

## Prerequisites

- Python **3.12** (`py -3.12`)
- Git
- Optional: TeX Live / MiKTeX (`latexmk`, `chktex`), Ollama + NVIDIA driver

## Install

```powershell
cd C:\path\to\GostCheck
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
normocontrol doctor
```

### ExecutionPolicy

If scripts are blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# or call explicitly:
powershell -ExecutionPolicy Bypass -File demo/run_demo.ps1 -Mode dry-run
```

### OneDrive / Cyrillic paths

Prefer a short ASCII repo path when possible. The tool uses `pathlib` and UTF-8;
NFD filenames are supported, but cloud-synced folders can lock files during builds.

## Smoke

```powershell
python -m pytest -q -m "not live"
normocontrol run tests/fixtures/demo/pass --provider disabled --out build/demo-pass
```
