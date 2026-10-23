#!/bin/bash
cd "$(dirname "$0")" || exit 1
cd hh-autoresponder || exit 1

source .venv/bin/activate
python3 scripts/inspect_sofi.py
