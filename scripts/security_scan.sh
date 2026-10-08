#!/usr/bin/env bash
# Cerca in tutta la storia git ciò che non deve diventare pubblico.
#
# Uso: scripts/security_scan.sh [indirizzo email ammesso nei commit]
# Esce con codice 1 se trova qualcosa. Non stampa mai il valore di una chiave.
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
allowed="${1:-$(git config user.email)}"
revs=$(git rev-list --all)
problems=0

report() { # titolo, risultato (vuoto = nessun problema)
  if [ -n "$2" ]; then
    printf '[PROBLEMA] %s\n%s\n' "$1" "$(printf '%s\n' "$2" | head -10 | sed 's/^/    /')"
    problems=$((problems + 1))
  else
    printf '[ok]       %s\n' "$1"
  fi
}

# Percorsi ignorati nelle ricerche sul contenuto: questo script contiene i pattern stessi.
skip=(':!scripts/security_scan.sh')

files=$(git log --all --name-only --format= | sort -u)

report "nessun file .env nella storia" \
  "$(printf '%s\n' "$files" | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$')"

report "nessun file di chiavi o credenziali nella storia" \
  "$(printf '%s\n' "$files" | grep -iE '\.(pem|key|p12|pfx)$|credential|secret|id_rsa')"

report "nessun file di dati nei branch del codice" \
  "$(git log --exclude=refs/heads/data --branches --name-only --format= | sort -u | grep -E '^data/|\.parquet$')"

if [ -f .env ]; then
  key=$(grep -E '^FRED_API_KEY=' .env | cut -d= -f2-)
  if [ -n "$key" ]; then
    in_files=$(git grep -l -F "$key" $revs 2>/dev/null | cut -d: -f2 | sort -u)
    in_messages=$(git log --all --format='%h %B' | grep -F "$key" | cut -c1-7)
    report "la chiave FRED di .env non compare in nessun commit" "$in_files$in_messages"
  fi
  report ".env è ignorato da git" "$(git check-ignore -q .env || echo '.env non è in .gitignore')"
fi

# Per questi due controlli si stampano solo file e riga, mai il contenuto.
report "nessun valore assegnato a una chiave API" \
  "$(git grep -n -I -iE '(api_?key|token|password|secret)[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9_\-]{16,}' $revs -- . "${skip[@]}" | cut -d: -f2,3 | sort -u)"

report "nessuna stringa che sembra una chiave (32+ caratteri esadecimali)" \
  "$(git grep -n -I -E '(^|[^0-9a-f])[0-9a-f]{32,}([^0-9a-f]|$)' $revs -- . "${skip[@]}" ':!results/' | cut -d: -f2,3 | sort -u)"

report "nessun percorso personale" \
  "$(git grep -n -I -E '/Users/[A-Za-z]|/home/[a-z]|C:\\\\Users' $revs -- . "${skip[@]}" | cut -d: -f2- | sort -u)"

report "solo l'indirizzo ammesso tra autori e committer ($allowed)" \
  "$(git log --all --format='%ae%n%ce' | sort -u | grep -v -F -x "$allowed" | grep -v -F 'github-actions[bot]@users.noreply.github.com')"

report "solo l'indirizzo ammesso nei tag" \
  "$(git for-each-ref refs/tags --format='%(taggeremail)' | tr -d '<>' | sort -u | grep -v '^$' | grep -v -F -x "$allowed")"

report "nessun indirizzo email personale nei file" \
  "$(git grep -n -I -E '[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail|yahoo|libero|icloud)\.[a-z]+' $revs -- . "${skip[@]}" | cut -d: -f2- | sort -u)"

if [ "$problems" -gt 0 ]; then
  echo "$problems controlli con problemi."
  exit 1
fi
echo "Nessun problema trovato in $(printf '%s\n' "$revs" | wc -l | tr -d ' ') commit."
