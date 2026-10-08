# Nowcasting del PIL italiano

Stima in tempo reale della crescita trimestrale del PIL dell'Italia a partire da indicatori mensili, con valutazione pseudo real-time dei modelli.

**Stato del progetto**: dati e modelli completati (Fasi 1 e 2). Valutazione e dashboard sono in arrivo; le sezioni corrispondenti sono segnate come da fare.

## Domanda di ricerca

Il PIL trimestrale esce circa 30 giorni dopo la fine del trimestre. Nel frattempo arrivano, con ritardi diversi, decine di indicatori mensili. Quanto migliorano la stima del trimestre in corso rispetto a un semplice modello autoregressivo, e a partire da quanti giorni prima della pubblicazione?

## Dati

Diciotto serie (lo spread è calcolato dai due rendimenti), tutte gratuite, registrate in [config/series.yaml](config/series.yaml) con codice, trasformazione e ritardo di pubblicazione.

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

La data di rilascio ha quattro origini:

| Origine | Significato | Copertura |
|---|---|---|
| `alfred` | prima pubblicazione dallo storico dei vintage ALFRED | Brent dal 2011, gas dal 2015 |
| `first_seen` | il dato è comparso tra due download: vale la data del download | da ottobre 2026 in avanti |
| `revision` | il valore di un periodo già noto è cambiato: nuova riga con la data del download | da ottobre 2026 in avanti |
| `estimated_lag` | fine del periodo più il ritardo di pubblicazione in vigore allora | il resto dello storico (circa il 96% delle righe) |

Un valore registrato non viene mai riscritto: una revisione aggiunge una riga, quindi lo snapshot di una data passata resta identico dopo ogni aggiornamento. Ogni esecuzione stampa l'impronta del dataset usato, così una valutazione è legata a una versione precisa dei dati.

I ritardi stimati seguono il calendario ISTAT dell'epoca e sono arrotondati per eccesso, perché una data troppo anticipata darebbe al modello informazione che non aveva. Dove il calendario è cambiato il registro distingue i regimi:

| Serie | Ritardo | Riscontro |
|---|---|---|
| PIL, stima preliminare | 46 giorni fino al 2017-Q4, poi 32 | 2011-Q4 uscito il 15 febbraio 2012; 2018-Q1 il 2 maggio 2018 |
| Vendite al dettaglio | 56 giorni fino al 2016, 43 nel 2017, poi 38 | luglio 2011 uscito il 23 settembre; gennaio 2017 il 15 marzo |
| Produzione industriale | 43 giorni | luglio 2011 uscito il 12 settembre |
| Commercio estero | 50 giorni | novembre 2011 uscito il 18 gennaio 2012 |
| Disoccupazione | 33 giorni | dicembre 2011 uscito il 31 gennaio 2012 |

Queste date reali sono verificate da un test: il ritardo stimato non deve precederle e non deve superarle di più di cinque giorni. Per rendimenti ed Euribor il ritardo è quello della fonte, non quello del mercato: il backtest vede gli stessi dati che vede il sistema dal vivo.

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
- **Nessuna osservazione esclusa dalla stima.** I modelli principali usano tutti i dati noti a ogni data, 2020 compreso: è ciò che un modello fissato in anticipo avrebbe fatto. Il costo è visibile: con il 2020 nel campione la deviazione standard della crescita del PIL passa da 0,73 a 2,06 e gli intervalli si allargano.
- **Variante ex post.** Ogni modello ha una versione `_expost` stimata senza marzo-settembre 2020. Usa un'informazione che nel 2020 non c'era, quindi serve solo a misurare quanto pesa il trattamento del Covid, non come risultato principale.

Specificazione del DFM:

- **Fiducie in differenze prime**. In livelli sono quasi a radice unitaria e finiscono per coincidere con il fattore: sui campioni che terminano nel 2008-2009 la stima diventa esplosiva (coefficiente autoregressivo sopra 1).
- **ESI e rendimento italiano esclusi**: sono combinazioni di serie già presenti (le fiducie settoriali; Bund più spread).
- **Stime rifiutate invece che usate**: se l'algoritmo EM non converge o il modello non è stazionario, il codice si ferma con un errore.
- **Parametri mai dal futuro**: una stima porta con sé la data del set informativo che l'ha prodotta e non può essere applicata a una data precedente.

#### Finestra di sviluppo (dati fino al 2011)

La specificazione del DFM è stata messa a punto guardando i risultati su questa finestra: la trasformazione delle fiducie è stata cambiata dopo aver visto le stime esplodere, e il numero di fattori è stato scelto qui. Gli errori riportati sotto non sono quindi una verifica indipendente. La verifica è il backtest dal 2012 in poi, per il quale tutte le scelte sono congelate. Le evidenze si riproducono con `python -m nowcast.pipeline select-factors`.

| Fattori | Varianza spiegata | ICp2 (Bai-Ng) | BIC del modello | RMSE a 90 giorni | a 60 giorni | a 30 giorni |
|---|---|---|---|---|---|---|
| 1 | 22% | **−0,053** | **5.705** | 0,875 | 0,800 | 0,736 |
| 2 | 34% | −0,020 | 5.725 | **0,806** | **0,684** | **0,668** |
| 3 | 44% | 0,030 | 5.749 | 0,922 | 0,735 | 0,773 |

L'RMSE è calcolato sui 16 trimestri 2008-2011, a 90, 60 e 30 giorni dalla pubblicazione del PIL. Sulla stessa finestra l'AR(1) ha RMSE 0,958 e il bridge 0,981, 0,765 e 0,618.

Le evidenze non sono concordi: i due criteri di informazione indicano un fattore, gli errori sulla finestra di sviluppo ne preferiscono due. Il modello principale ha **un fattore con dinamica VAR(1)**, seguendo i criteri formali e la parsimonia; quello a due fattori entra nel backtest alla pari, come alternativa dichiarata in anticipo. Un secondo ritardo nella dinamica del fattore non migliora il BIC.

Sulla stessa finestra è stata provata e scartata una regola automatica per gli outlier (distanza dalla mediana oltre 10 volte lo scarto interquartile): sui campioni corti del 2009 trattava la crisi come anomalia e produceva un errore di 3,4 punti su un trimestre.

### Valutazione

Da fare (Fase 3): backtest a 90, 60 e 30 giorni dalla pubblicazione del PIL, RMSE, MAE, test di Diebold-Mariano, risultati con e senza il 2020-2021.

## Risultati

Da fare.

## Limiti

- **Pseudo real-time, non real-time.** Per lo storico precedente al primo download (8 ottobre 2026) i valori sono quelli già rivisti disponibili quel giorno: il backtest rispetta il calendario delle pubblicazioni ma non le revisioni. Parametri e standardizzazione usano quindi valori che allora non esistevano, e il verso della distorsione sull'accuratezza non è garantito. Da ottobre 2026 in poi le revisioni sono registrate.
- **Date di rilascio in gran parte stimate.** Circa il 96% delle righe ha una data ricavata dal ritardo tipico. I ritardi sono riscontrati su alcune date reali, non su tutto il calendario: gli orizzonti del backtest hanno una tolleranza di qualche giorno.
- **Date nazionali, fonte europea.** I riscontri riguardano i comunicati ISTAT, mentre i dati arrivano da Eurostat, che può pubblicarli più tardi.
- **Fiducia dei consumatori.** L'8 ottobre 2026 il dato di settembre non era disponibile, a differenza delle altre inchieste: il ritardo zero potrebbe essere ottimistico e va verificato sul calendario della fonte.
- **HICP.** Il ritardo di tre giorni corrisponde alla stima flash; il valore usato è quello successivo, rivisto.
- **Edizioni storiche del PIL non integrate.** ISTAT pubblica le edizioni dei conti trimestrali dal 2014, con cui si potrebbe valutare contro la prima stima invece che contro il dato di oggi.
- **Finestra di sviluppo non indipendente.** I 16 trimestri 2008-2011 sono serviti a scegliere la specificazione e includono la crisi del 2008-2009.
- **Intervalli dei modelli.** La deviazione standard del bridge e degli AR considera solo l'errore della regressione, non l'incertezza sui mesi completati né quella dei parametri. Gli intervalli della dashboard si baseranno sugli errori del backtest.
- **Campione.** Vendite al dettaglio dal 2000 e commercio estero dal 2002 limitano il campione comune a circa 98 trimestri.
- **Aprile 2020.** Le inchieste sulla fiducia non furono condotte; il mese è mancante.

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
