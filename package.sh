#!/usr/bin/env bash
# Gera out/<pasta>.zip no mesmo formato do Decky (defaults/ vai para a raiz do plugin).
set -euo pipefail
cd "$(dirname "$0")"
NAME="${1:-hyperhdr-toggle}"
${PNPM:-pnpm} build
rm -rf "out/$NAME" "out/$NAME.zip"
mkdir -p "out/$NAME/dist"
cp dist/index.js "out/$NAME/dist/"
cp main.py plugin.json package.json LICENSE README.md "out/$NAME/"
cp -r py_modules "out/$NAME/"
cp -r defaults/. "out/$NAME/"
find "out/$NAME" -name __pycache__ -prune -exec rm -rf {} +
(cd out && python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1],'zip','.',sys.argv[1])" "$NAME")
echo "out/$NAME.zip"
