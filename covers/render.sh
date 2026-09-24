#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
python3 build.py
R=/Users/teja.kummarikuntla/Dev/skills/blog-banner-generator/scripts/render_png.sh
bash "$R" cover-devto.html    1000 420 cover-devto.png
bash "$R" cover-hashnode.html 1600 840 cover-hashnode.png
