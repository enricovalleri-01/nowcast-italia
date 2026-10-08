# AGENTS.md

## Ruolo
Codex fa solo review: non modifica file e non fa commit.

## Branch
- `main`: solo lavoro approvato.
- `claude/<attività>`: l'unico branch dove si scrive, e lo fa solo Claude Code.
- Codex legge quel branch in sola lettura. Eventuali correzioni proposte vanno su `codex/review-<attività>`, unito solo dall'utente.
- `data`: archivio dei dati e registro delle stime. Ci scrive solo il workflow automatico di GitHub Actions, che non scrive mai su `main` né su altri branch. Contiene solo la cartella `data/`, mai codice, e cresce solo per aggiunta: il workflow esegue `update-data`, mai `init-data` o `redate-data`.

## Regole del progetto
- Nessuna credenziale o dato di accesso nei file del progetto.

## Output della review
Elenco di problemi con file e riga, dal più grave al meno grave; niente riscritture.
