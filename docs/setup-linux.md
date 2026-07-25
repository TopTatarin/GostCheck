# Setup — Linux

## Prerequisites

- Python **3.12**
- Git
- Required for the same formal gate as CI: the TeX packages below
- Optional: Ollama

On Ubuntu 24.04, install the explicit CI toolchain:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends -y \
  biber \
  chktex \
  fonts-texgyre \
  latexmk \
  texlive-bibtex-extra \
  texlive-fonts-recommended \
  texlive-lang-cyrillic \
  texlive-latex-extra \
  texlive-xetex
command -v latexmk chktex xelatex biber
kpsewhich biblatex-gost.sty
fc-match "TeX Gyre Termes" | grep -F "TeX Gyre Termes"
```

CI does not install proprietary Times New Roman. Synthetic classes keep the
formal Times New Roman declaration but compile with TeX Gyre Termes through
`\IfFontExistsTF` when Times New Roman is absent.

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

The GitHub `formal-gate` always installs and verifies this TeX toolchain.
Missing `latexmk`, `chktex`, XeLaTeX, `biber`, `biblatex-gost`, or TeX Gyre
Termes is a hard setup failure rather than a degraded success.
