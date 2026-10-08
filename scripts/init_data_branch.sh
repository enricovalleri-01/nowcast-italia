#!/usr/bin/env bash
# Crea in locale il branch `data` con l'archivio iniziale. Non fa push.
#
# Va eseguito una sola volta, a mano: il workflow automatico non crea mai l'archivio, lo
# aggiorna soltanto. Il branch nasce senza storia in comune con il codice e contiene solo
# la cartella data/ (archivio, versioni congelate, registro delle stime).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if git show-ref --verify --quiet refs/heads/data; then
  echo "Il branch data esiste già: non lo ricreo." >&2
  exit 1
fi
for item in data/observations.parquet data/versions data/nowcast_log.csv; do
  [ -e "$item" ] || { echo "Manca $item: eseguire prima init-data e nowcast." >&2; exit 1; }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git init -q -b data "$work"
mkdir "$work/data"
cp -Rp data/observations.parquet data/versions data/nowcast_log.csv "$work/data/"
cat > "$work/README.md" <<'TXT'
# Archivio dei dati

Questo branch contiene solo dati: l'archivio delle osservazioni con le date di rilascio
(`data/observations.parquet`), una copia immutabile di ogni versione (`data/versions/`,
nominata con l'impronta del contenuto) e il registro delle stime (`data/nowcast_log.csv`).

Dopo il primo commit, creato a mano, ci scrive solo il workflow settimanale di GitHub
Actions, che aggiunge righe e non modifica quelle esistenti. Il codice è sul branch `main`.
TXT
printf 'data/raw/\n' > "$work/.gitignore"

git -C "$work" add -A
git -C "$work" -c user.name="$(git config user.name)" -c user.email="$(git config user.email)" \
  commit -q -m "Archivio iniziale dei dati e registro delle stime"
git fetch -q "$work" data:data

echo "Branch data creato in locale (nessun push):"
git log --format='  %h %ae %s' -1 data
git ls-tree -r --name-only data | sed 's/^/  /'
