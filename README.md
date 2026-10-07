# Nowcasting del PIL italiano

Stima in tempo reale della crescita trimestrale del PIL dell'Italia a partire da indicatori mensili, con valutazione pseudo real-time dei modelli.

**Stato del progetto**: dati completati (Fase 1). Modelli, valutazione e dashboard sono in arrivo; le sezioni corrispondenti sono segnate come da fare.

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

Da fare (Fase 2): benchmark autoregressivi, bridge equations, dynamic factor model a frequenza mista.

### Valutazione

Da fare (Fase 3): backtest a 90, 60 e 30 giorni dalla pubblicazione del PIL, RMSE, MAE, test di Diebold-Mariano, risultati con e senza il 2020-2021.

## Risultati

Da fare.

## Limiti

- **Pseudo real-time, non real-time**: la tabella registra quando un dato è uscito, ma il valore è quello di oggi, già rivisto. Il backtest rispetta il calendario delle pubblicazioni e ignora le revisioni, quindi tende a sovrastimare l'accuratezza che si sarebbe ottenuta davvero.
- **Date di rilascio in gran parte stimate**: per quasi tutte le serie lo storico usa un ritardo fisso, mentre il calendario reale varia di qualche giorno. Gli orizzonti del backtest vanno letti con questa tolleranza.
- **Data del PIL**: 30 giorni dalla fine del trimestre, cioè la stima preliminare ISTAT. Le edizioni storiche dei conti trimestrali ISTAT, che permetterebbero di valutare contro la prima stima, non sono ancora integrate.
- **Campione**: vendite al dettaglio dal 2000 e commercio estero dal 2002 limitano il campione comune a circa 98 trimestri.
- **Aprile 2020**: le inchieste sulla fiducia non furono condotte; il mese è mancante.
- **Fiducia dei consumatori**: l'8 ottobre 2026 il dato di settembre non era ancora disponibile, a differenza delle altre inchieste. Il ritardo zero assegnato alla serie potrebbe essere ottimistico.

## Come eseguire

```bash
conda create -n nowcast python=3.12
conda activate nowcast
pip install -e ".[dev]"
cp .env.example .env        # poi inserire la chiave FRED (gratuita)
python -m nowcast.pipeline update-data
pytest
```

I dati scaricati finiscono in `data/`, esclusa da git. Le API di Eurostat e BCE non richiedono chiavi.
