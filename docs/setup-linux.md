# Setup — Linux

## Prerequisites

- Python **3.12**
- Git
- Optional: TeX Live (`latexmk`, `chktex`), Ollama

## Install

```bash
cd /path/to/GostCheck
python3.12 -m venv .venv312
source .venv312/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
normocontrol doctor
```

## Smoke

```bash
python -m pytest -q -m "not live"
normocontrol run tests/fixtures/demo/pass --provider disabled --out build/demo-pass
bash demo/run_demo.sh --mode dry-run
```

Docker/TeX Live are optional for the PoC formal-gate on GitHub-hosted runners:
missing `latexmk` is marked degraded and must not block the documented demo
fixtures that run extraction without a full TeX install.
