# Nowcasting del PIL italiano

Stima in tempo reale della crescita trimestrale del PIL dell'Italia a partire da indicatori mensili, con valutazione pseudo real-time dei modelli.

**Stato del progetto**: dati e modelli completati (Fasi 1 e 2). Valutazione e dashboard sono in arrivo; le sezioni corrispondenti sono segnate come da fare.

## Domanda di ricerca

Il PIL trimestrale esce circa 30 giorni dopo la fine del trimestre. Nel frattempo arrivano, con ritardi diversi, decine di indicatori mensili. Quanto migliorano la stima del trimestre in corso rispetto a un semplice modello autoregressivo, e a partire da quanti giorni prima della pubblicazione?

## Dati

Diciotto serie, tutte gratuite, registrate in [config/series.yaml](config/series.yaml) con codice, trasformazione e ritardo di pubblicazione.

| Blocco | Serie | Fonte |
|---|---|---|
| Target | PIL in volume, destagionalizzato (dal 1996) | Eurostat |
| Attività reale | Produzione industriale, vendite al dettaglio, esportazioni, importazioni | Eurostat |
| Lavoro | Tasso di disoccupazione | Eurostat |
| Fiducia | ESI, fiducia di industria, servizi e consumatori (Commissione Europea) | Eurostat |
| Prezzi | HICP | Eurostat |
| Finanza | Rendimenti a 10 anni di Italia e Germania, spread BTP-Bund, Euribor a 3 mesi, tasso BCE sui depositi | Eurostat, BCE |
| Energia | Brent, gas naturale europeo | FRED |

Scelte sulle fonti:

- **Niente PMI**: sono dati a pagamento di S&P Global. Li sostituiscono le inchieste della Commissione Europea.
- **PIL in livelli**: la crescita t/t è calcolata dai volumi concatenati, perché la variazione pubblicata da Eurostat è arrotondata a un decimale.
- **HICP**: dal 2026 Eurostat usa la classificazione ECOICOP v2 (dataset `prc_hicp_minr`, base 2025=100); il dataset precedente è fermo a dicembre 2025.
- **Spread**: differenza tra medie mensili dei rendimenti a 10 anni, non il dato giornaliero di mercato.
- **Gas**: prezzo europeo di fonte FMI, mensile. Non è stato trovato un TTF giornaliero gratuito.

## Metodo

### Date di rilascio e ragged edge

Ogni osservazione è salvata con la data in cui è diventata pubblica. La funzione `snapshot(osservazioni, data)` restituisce solo ciò che era noto a quella data ed è l'unico accesso ai dati previsto per modelli e backtest: così il set informativo di qualsiasi giorno passato si ricostruisce senza guardare avanti. Nel panel mensile le serie più lente restano mancanti negli ultimi mesi (il "ragged edge").

La data di rilascio ha tre origini, dalla più alla meno affidabile:

| Origine | Significato | Copertura |
|---|---|---|
| `alfred` | prima pubblicazione dallo storico dei vintage ALFRED | Brent dal 2011, gas dal 2015 |
| `first_seen` | il dato è comparso tra due download: vale la data del download | da ottobre 2026 in avanti, per tutte le serie |
| `estimated_lag` | fine del periodo più il ritardo tipico della serie | tutto il resto dello storico |

I ritardi tipici sono stati controllati contro la disponibilità effettiva dei dati l'8 ottobre 2026. Per i rendimenti e l'Euribor il ritardo è quello della fonte, non quello del mercato: il backtest vede così gli stessi dati che vedrà il sistema quando gira dal vivo.

### Modelli

Tutti i modelli ricevono lo stesso set informativo e restituiscono la crescita t/t prevista con una deviazione standard.

| Modello | Cosa usa | Come funziona |
|---|---|---|
| Media storica | solo il PIL | media della crescita passata |
| AR(1), AR(2) | solo il PIL | autoregressione OLS; se manca anche il trimestre precedente prevede due passi avanti |
| Bridge | produzione industriale, vendite al dettaglio, ESI | completa i mesi mancanti di ogni indicatore con un AR (ordine scelto con il BIC), porta i livelli a media trimestrale e stima una regressione OLS sul PIL |
| DFM | 15 serie mensili più il PIL | fattore comune mensile stimato con l'algoritmo EM (`DynamicFactorMQ` di statsmodels); il PIL trimestrale entra con l'aggregazione di Mariano e Murasawa e i dati mancanti sono gestiti dal filtro di Kalman |

Scelte comuni:

- **Indicatori del bridge fissati a priori**, non selezionati sul periodo di valutazione: due indicatori quantitativi e la fiducia sintetica.
- **Covid escluso dalla stima, non dalle previsioni**: le osservazioni tra marzo e settembre 2020 non entrano nella stima dei parametri, ma restano nei dati su cui si calcola il nowcast. Con il 2020 dentro, la deviazione standard del PIL passa da 0,73 a 2,06 e ogni parametro ne viene dominato.

Specificazione del DFM:

- **Fiducie in differenze prime**. In livelli sono quasi a radice unitaria e finiscono per coincidere con il fattore: sui campioni che terminano nel 2008-2009 la stima diventa esplosiva (coefficiente autoregressivo sopra 1) e l'errore di validazione supera le migliaia di punti. In differenze il modello resta stazionario su tutta la finestra.
- **ESI e rendimento italiano esclusi**: sono combinazioni di serie già presenti (le fiducie settoriali; Bund più spread).
- **Controllo di stazionarietà**: una stima con radice maggiore o uguale a 1 viene rifiutata con un errore, invece di produrre un numero.

Numero di fattori. La scelta usa solo dati fino al 2011, prima dell'inizio del backtest, e si riproduce con `python -m nowcast.pipeline select-factors`.

| Fattori | Varianza spiegata | ICp2 (Bai-Ng) | BIC del modello | RMSE a 90 giorni | a 60 giorni | a 30 giorni |
|---|---|---|---|---|---|---|
| 1 | 22% | **−0,053** | **5.668** | **0,855** | 0,856 | 0,783 |
| 2 | 34% | −0,020 | 5.689 | 0,867 | **0,768** | **0,748** |
| 3 | 44% | 0,030 | 5.715 | 0,921 | 0,935 | 0,878 |

L'RMSE è l'errore pseudo fuori campione sui 16 trimestri 2008-2011, a 90, 60 e 30 giorni dalla pubblicazione del PIL. Sulla stessa finestra l'AR(1) ha RMSE 0,958 e il bridge 1,035, 0,965 e 0,758.

Il modello principale ha **un fattore con dinamica VAR(1)**: lo indicano entrambi i criteri di informazione, mentre in validazione uno e due fattori sono sostanzialmente pari e tre sono peggiori. Un secondo ritardo nella dinamica del fattore non migliora il BIC. Il modello a due fattori resta nel backtest come controllo di robustezza.

### Valutazione

Da fare (Fase 3): backtest a 90, 60 e 30 giorni dalla pubblicazione del PIL, RMSE, MAE, test di Diebold-Mariano, risultati con e senza il 2020-2021.

## Risultati

Da fare.

## Limiti

- **Pseudo real-time, non real-time**: la tabella registra quando un dato è uscito, ma il valore è quello di oggi, già rivisto. Il backtest rispetta il calendario delle pubblicazioni e ignora le revisioni, quindi tende a sovrastimare l'accuratezza che si sarebbe ottenuta davvero.
- **Date di rilascio in gran parte stimate**: per quasi tutte le serie lo storico usa un ritardo fisso, mentre il calendario reale varia di qualche giorno. Gli orizzonti del backtest vanno letti con questa tolleranza.
- **Data del PIL**: 30 giorni dalla fine del trimestre, cioè la stima preliminare ISTAT. Le edizioni storiche dei conti trimestrali ISTAT, che permetterebbero di valutare contro la prima stima, non sono ancora integrate.
- **Campione**: vendite al dettaglio dal 2000 e commercio estero dal 2002 limitano il campione comune a circa 98 trimestri.
- **Intervalli dei modelli**: la deviazione standard del bridge e degli AR considera solo l'errore della regressione, non l'incertezza sui mesi completati né quella dei parametri. Gli intervalli della dashboard si baseranno sugli errori del backtest.
- **Finestra Covid scelta a posteriori**: escludere marzo-settembre 2020 dalla stima è una decisione presa sapendo com'è andata; nel 2020 nessuno aveva questa informazione.
- **Validazione corta**: i 16 trimestri usati per scegliere i fattori includono la crisi del 2008-2009 e non distinguono uno da due fattori.
- **Aprile 2020**: le inchieste sulla fiducia non furono condotte; il mese è mancante.
- **Fiducia dei consumatori**: l'8 ottobre 2026 il dato di settembre non era ancora disponibile, a differenza delle altre inchieste. Il ritardo zero assegnato alla serie potrebbe essere ottimistico.

## Come eseguire

```bash
conda create -n nowcast python=3.12
conda activate nowcast
pip install -e ".[dev]"
cp .env.example .env        # poi inserire la chiave FRED (gratuita)
python -m nowcast.pipeline update-data      # scarica e aggiorna i dati
python -m nowcast.pipeline nowcast          # stima del trimestre in corso
python -m nowcast.pipeline select-factors   # evidenze sulla scelta dei fattori
pytest
```

I dati scaricati finiscono in `data/`, esclusa da git. Le API di Eurostat e BCE non richiedono chiavi.
