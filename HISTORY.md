# Storia del repository

## Riscrittura degli autori (8 ottobre 2026)

Prima di rendere pubblico il repository, l'indirizzo email personale presente come autore e committer di tutti i commit è stato sostituito con l'indirizzo `noreply` di GitHub. La riscrittura ha toccato solo i metadati: i contenuti di ogni commit sono identici, come verificato confrontando gli alberi dei file prima e dopo.

Cambiando i metadati cambiano però gli identificativi dei commit. I file prodotti prima della riscrittura riportano i vecchi identificativi e **non sono stati modificati**:

- `results/backtest.csv`, colonna `specification_commit`: `0a09f41`
- `results/report.md`, riga di intestazione: `0a09f41`

Quel valore corrisponde oggi al commit `18fb18c`, su cui si trova il tag `protocollo-v1.1`.

### Corrispondenza tra vecchi e nuovi identificativi

| Prima | Dopo | Commit |
|---|---|---|
| `76d51e5` | `ad0e3c4` | Aggiunge AGENTS.md con le regole per la review di Codex |
| `3a24b5d` | `f3539c7` | Aggiunge la fase dati: registro delle serie, download e date di rilascio |
| `978430f` | `515ee79` | Aggiunge i modelli: benchmark, bridge equation e DFM a frequenza mista |
| `69545a6` | `0c40e9c` | Corregge i problemi della review di Codex su calendario, vintage e stima |
| `579fe7a` | `3cd6a89` | Fissa il protocollo di valutazione prima del backtest |
| `0a09f41` | `18fb18c` | Corregge la seconda review: archivio immutabile, calendario, convergenza EM |
| `9603600` | `58f77e8` | Aggiunge la valutazione: backtest del protocollo, test e risultati |
| `5d278dc` | `69c8c08` | Aggiunge intervalli calibrati sul backtest e registro delle stime |

### Tag

I tre tag sono stati ricreati sui commit corrispondenti, con lo stesso messaggio e la stessa data.

| Tag | Prima | Dopo |
|---|---|---|
| `protocollo-v1` | `579fe7a` | `3cd6a89` |
| `protocollo-v1.1` | `0a09f41` | `18fb18c` |
| `fase-3-risultati` | `9603600` | `58f77e8` |

### Come verificare

La specificazione usata dal backtest non dipende dall'identificativo ma dal contenuto: il comando `backtest` confronta dati, modelli e registro delle serie con quelli del tag `protocollo-v1.1` e si ferma se differiscono. L'impronta del dataset (`ef2b22705503`) è calcolata sul contenuto dei dati e non è cambiata.
