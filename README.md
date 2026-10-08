# Archivio dei dati

Questo branch contiene solo dati: l'archivio delle osservazioni con le date di rilascio
(`data/observations.parquet`), una copia immutabile di ogni versione (`data/versions/`,
nominata con l'impronta del contenuto) e il registro delle stime (`data/nowcast_log.csv`).

Dopo il primo commit, creato a mano, ci scrive solo il workflow settimanale di GitHub
Actions, che aggiunge righe e non modifica quelle esistenti. Il codice è sul branch `main`.
