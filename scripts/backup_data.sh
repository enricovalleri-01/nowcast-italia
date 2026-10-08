#!/usr/bin/env bash
# Copia l'archivio dei dati e il registro delle stime in una cartella fuori dal repository.
#
# Uso: scripts/backup_data.sh [cartella di destinazione]
# Predefinita: ../<nome del progetto>_backup, accanto al repository.
# Ogni esecuzione crea una sottocartella nuova con data e ora e verifica le copie.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
base="${1:-$root/../$(basename "$root")_backup}"
mkdir -p "$base"
base="$(cd "$base" && pwd)"

case "$base/" in
  "$root"/*) echo "La destinazione deve stare fuori dal repository: $base" >&2; exit 1 ;;
esac

dest="$base/data-$(date +%Y%m%d-%H%M%S)"
if [ -e "$dest" ]; then
  echo "La cartella esiste già, non la sovrascrivo: $dest" >&2
  exit 1
fi

items=()
for item in data/versions data/observations.parquet data/nowcast_log.csv; do
  [ -e "$root/$item" ] && items+=("$item")
done
if [ "${#items[@]}" -eq 0 ]; then
  echo "Niente da copiare: data/ è vuota." >&2
  exit 1
fi

mkdir -p "$dest/data"
for item in "${items[@]}"; do
  cp -Rp "$root/$item" "$dest/data/"
done

# Verifica: stessi file e stesso contenuto.
for item in "${items[@]}"; do
  diff -rq "$root/$item" "$dest/$item" >/dev/null || { echo "Copia non identica: $item" >&2; exit 1; }
done
(cd "$dest" && find data -type f -exec shasum -a 256 {} + | sort -k2 > SHA256SUMS)

echo "Backup verificato: $dest"
echo "File copiati: $(find "$dest/data" -type f | wc -l | tr -d ' ')"
