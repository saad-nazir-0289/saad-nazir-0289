# Profile artwork builder

This script regenerates the SVG artwork used by the profile README.

## Requirements

- Python 3.11 or newer.
- A local checkout of the portfolio site, supplied through `--site`.
- The font files bundled in this directory.

## Setup

Run these commands from the repository root:

```bash
python -m venv .venv
```

Activate the environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the pinned dependencies:

```bash
python -m pip install -r scripts/design/requirements.txt
```

## Regenerate the artwork

Pass the path to a local checkout of the portfolio site. The builder reads its generated project and blog data and public images, then writes the resulting SVG files into this repository's `assets/` directory.

```bash
python scripts/design/build.py --site ../Saad-Portfolio
```

The builder only reads from the supplied site directory. Review the generated asset changes with `git diff -- assets/` before committing them.
