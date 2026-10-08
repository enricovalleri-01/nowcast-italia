# Nowcasting del PIL italiano

Stima in tempo reale della crescita trimestrale del PIL dell'Italia a partire da indicatori mensili, con valutazione pseudo real-time dei modelli.

**Stato del progetto**: dati e modelli completati (Fasi 1 e 2), protocollo di valutazione fissato. Backtest e dashboard sono in arrivo; i risultati sono segnati come da fare.

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
| `first_seen` | il periodo è comparso a un download: vale la data del download | da ottobre 2026 in avanti |
| `revision` | il valore di un periodo già noto è cambiato: nuova riga con la data del download | da ottobre 2026 in avanti |
| `estimated_lag` | fine del periodo più il ritardo di pubblicazione in vigore allora | il resto dello storico (circa il 96% delle righe) |

#### Un archivio che cresce solo per aggiunta

Ogni riga è una versione di un'osservazione, con la data di acquisizione e un numero progressivo. Lo snapshot prende, per ogni periodo, l'ultima versione pubblicata entro la data richiesta; a parità di data prevale la più recente, quindi il risultato non dipende dall'ordine delle righe. Tre comandi distinti modificano l'archivio:

| Comando | Cosa fa | Effetto sugli snapshot passati |
|---|---|---|
| `update-data` | aggiunge nuovi periodi e revisioni, datati al giorno del download | nessuno: le righe esistenti non vengono toccate |
| `init-data` | importa lo storico di una serie non ancora in archivio, con date stimate | li cambia: nuova versione del dataset |
| `redate-data` | riapplica il calendario di `series.yaml` alle date stimate | li cambia: nuova versione del dataset |

Solo l'aggiornamento ordinario garantisce l'invarianza del passato. Un periodo che compare per la prima volta a un aggiornamento prende la data di quel giorno anche se è più vecchio dei dati già presenti: non c'è prova che fosse pubblico prima. Ogni salvataggio conserva una copia immutabile in `data/versions/`, nominata con l'impronta di schema e contenuto; una valutazione legge la copia della propria versione e ne verifica l'impronta.

#### Calendario

I ritardi stimati seguono il calendario ISTAT dell'epoca. La regola è che la data stimata non deve mai precedere quella reale, perché darebbe al modello informazione che non aveva; può seguirla di qualche giorno.

| Serie | Ritardo | Riscontri |
|---|---|---|
| PIL, stima preliminare | 46 giorni fino al 2017-Q4, poi 32 | 2011-Q4 uscito il 15 febbraio 2012; 2018-Q1 il 2 maggio 2018 |
| Vendite al dettaglio | 56 giorni fino al 2016, poi 44 | luglio 2011 il 23 settembre; gennaio 2018 il 14 marzo; gennaio 2024 il 15 marzo |
| Produzione industriale | 43 giorni | luglio 2011 uscito il 12 settembre |
| Commercio estero | 50 giorni | novembre 2011 uscito il 18 gennaio 2012 |
| Disoccupazione | 33 giorni | dicembre 2011 uscito il 31 gennaio 2012 |
| HICP, stima flash | 7 giorni | gennaio 2019 uscito il 4 febbraio |

Per le vendite al dettaglio un ritardo fisso è una forzatura: dal 2017 i comunicati di gennaio sono usciti tra 33 e 44 giorni dopo la fine del mese. Il valore scelto copre il caso peggiore riscontrato, quindi in molti mesi il dato entra nel set informativo fino a 11 giorni dopo la pubblicazione reale. È un errore in direzione prudente, che penalizza soprattutto il bridge.

Ventuno date reali sono verificate da un test: il ritardo stimato non deve precederle e non deve superarle di più di 12 giorni. Per rendimenti ed Euribor il ritardo è quello della fonte, non quello del mercato: il backtest vede gli stessi dati che vede il sistema dal vivo.

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
- **Stime rifiutate invece che usate**: il codice si ferma con un errore se il criterio di convergenza dell'EM non è raggiunto (per iterazioni esaurite o per un calo della verosimiglianza) o se il modello non è stazionario.
- **Parametri mai dal futuro né da un altro modello**: una stima porta con sé la data del set informativo e la specificazione che l'hanno prodotta (fattori, ordine, trasformazioni, finestra esclusa) e non può essere applicata a una data precedente o a una specificazione diversa.

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

## Protocollo di valutazione

Versione 1, fissata con il tag git `protocollo-v1` prima di eseguire il backtest. Da quel commit la specificazione dei modelli e le regole qui sotto non cambiano in base ai risultati. Ogni cambiamento successivo va elencato in "Modifiche successive al protocollo", con data, motivo e l'indicazione se è stato deciso dopo aver visto i risultati.

### Oggetto

- **Variabile**: crescita t/t del PIL italiano in volume, destagionalizzato e corretto per il calendario.
- **Valore realizzato**: quello presente nel dataset congelato, cioè l'ultima versione disponibile e non la prima stima pubblicata.
- **Dataset**: quello scaricato l'8 ottobre 2026, impronta `ef2b22705503` (vedi le modifiche successive). Il backtest legge la copia congelata in `data/versions/` e non aggiorna i dati.

### Modelli

La specificazione è quella del codice e di `config/series.yaml` al commit del tag.

| Ruolo | Modelli |
|---|---|
| Benchmark principale | `ar1` |
| Altri benchmark | `media_storica`, `ar2` |
| Modelli valutati | `bridge`, `dfm_k1` (principale), `dfm_k2` (alternativa dichiarata) |
| Analisi secondaria | le varianti `_expost` di tutti i modelli, stimate senza marzo-settembre 2020 |

### Disegno del backtest

- **Trimestri**: dal 2012-Q1 al 2026-Q2, 58 trimestri. I dati fino al 2011 sono serviti a sviluppare i modelli e restano fuori.
- **Orizzonti**: 90, 60 e 30 giorni prima della data di pubblicazione del PIL del trimestre, letta dalla tabella delle osservazioni. Poiché la stima preliminare usciva a 45 giorni fino al 2017 e a 30 dopo, lo stesso orizzonte cade in un punto diverso del trimestre nei due periodi: a 30 giorni dalla pubblicazione si è 16 giorni dopo la fine del trimestre fino al 2017, 2 giorni dopo dal 2018.
- **Set informativo**: `snapshot` alla data dell'orizzonte, senza eccezioni.
- **Stima**: finestra espandente dal 2000, parametri ristimati a ogni data. Nessun riuso di parametri tra date.
- **Fallimenti**: se un modello rifiuta la stima (EM non convergente, modello non stazionario) la previsione resta mancante, con il motivo registrato. Non viene sostituita. Il numero di fallimenti è riportato per modello e orizzonte.

### Metriche

Errore = previsione − valore realizzato. Per ogni modello e orizzonte: RMSE, MAE, errore medio e RMSE relativo a quello di `ar1`. I confronti tra modelli usano solo i trimestri in cui tutti i modelli confrontati hanno una previsione.

### Finestre

| Finestra | Trimestri | Uso |
|---|---|---|
| Completa | 2012-Q1 – 2026-Q2 (58) | risultato principale |
| Senza 2020-2021 | 50 | risultato principale |
| 2012-2019, 2020-2021, 2022-2026 | 32, 8, 18 | analisi di dove i modelli falliscono |

Le due finestre principali hanno pari peso: nella prima l'RMSE è dominato dal 2020, nella seconda misura i periodi ordinari.

### Test statistici

- **Test**: Diebold-Mariano con la correzione per piccoli campioni di Harvey, Leybourne e Newbold, a due code, distribuzione t con n − 1 gradi di libertà.
- **Perdita**: errore quadratico (principale) ed errore assoluto (secondaria).
- **Varianza di lungo periodo**: nucleo rettangolare troncato a h − 1, dove h è il numero massimo di trimestri tra l'ultimo PIL noto e il trimestre previsto. Sul dataset congelato h vale 1 a 60 e 30 giorni e 2 a 90 giorni (un solo caso).
- **Confronti confermativi**: `bridge` contro `ar1` e `dfm_k1` contro `ar1`, ai tre orizzonti e sulle due finestre principali: 12 test. Tutti gli altri confronti sono esplorativi.
- **Avvertenze**: nessuna correzione per confronti multipli; con 50-58 osservazioni la potenza è bassa; con stima a finestra espandente il test va letto come confronto tra metodi di previsione, non tra modelli veri.

### Cosa viene salvato

Una riga per modello, trimestre e orizzonte con: previsione e deviazione standard, valore realizzato, data dell'orizzonte (`as_of`), data di pubblicazione del PIL, impronta del dataset, commit del codice ed esito (con il motivo in caso di fallimento).

### Modifiche successive al protocollo

**8 ottobre 2026, dopo il tag `protocollo-v1` e prima di eseguire il backtest.** Nessun risultato del backtest esisteva quando sono state decise: nascono dalla seconda review del codice.

| Modifica | Motivo | Effetto |
|---|---|---|
| Vendite al dettaglio: ritardo di 44 giorni dal 2017 (prima 43 nel 2017 e 38 dal 2018) | il regime a 38 giorni anticipava di quattro giorni i comunicati di gennaio e febbraio 2018 | 115 date di rilascio spostate in avanti |
| HICP: ritardo di 7 giorni (prima 3) | la stima flash di gennaio 2019 uscì il 4 febbraio | 369 date di rilascio spostate in avanti |
| Dataset: impronta `ef2b22705503` (prima `56a8dddb28d8`) | conseguenza delle due righe sopra e del nuovo schema dell'archivio | stessi 7.109 periodi e stessi valori; cambiano solo quelle 484 date |
| Controllo di convergenza dell'EM basato sul criterio effettivo, non sul numero di iterazioni | il controllo precedente poteva rifiutare stime convergenti e accettarne di non convergenti | cambia la classificazione dei fallimenti, non i modelli |

Il commit con queste modifiche è marcato dal tag `protocollo-v1.1`, che è la versione eseguita dal backtest; `protocollo-v1` resta sul commit originale.

Non cambiano i modelli, gli orizzonti, le metriche, le finestre né i test. Gli errori sulla finestra di sviluppo, ricalcolati sul nuovo dataset, sono identici a quelli riportati sopra; la scelta di un fattore non è stata rimessa in discussione.

## Risultati

Da fare: il backtest non è ancora stato eseguito.

## Limiti

- **Pseudo real-time, non real-time.** Per lo storico precedente al primo download (8 ottobre 2026) i valori sono quelli già rivisti disponibili quel giorno: il backtest rispetta il calendario delle pubblicazioni ma non le revisioni. Parametri e standardizzazione usano quindi valori che allora non esistevano, e il verso della distorsione sull'accuratezza non è garantito. Da ottobre 2026 in poi le revisioni sono registrate.
- **Date di rilascio in gran parte stimate.** Circa il 96% delle righe ha una data ricavata da un ritardo fisso, riscontrato su 21 date reali e non sull'intero calendario. Un ritardo fisso non può seguire un calendario che oscilla: dove è stato trovato un anticipo è stato allargato, ma altri anticipi di qualche giorno restano possibili, e per le vendite al dettaglio il dato entra fino a 11 giorni tardi.
- **Date nazionali, fonte europea.** I riscontri riguardano i comunicati ISTAT, mentre i dati arrivano da Eurostat, che può pubblicarli più tardi.
- **Fiducia dei consumatori.** L'8 ottobre 2026 il dato di settembre non era disponibile, a differenza delle altre inchieste: il ritardo zero potrebbe essere ottimistico e va verificato sul calendario della fonte.
- **HICP.** Il ritardo di sette giorni corrisponde alla stima flash; il valore usato è quello successivo, rivisto.
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
python -m nowcast.pipeline init-data        # prima volta: importa lo storico
python -m nowcast.pipeline update-data      # aggiornamenti successivi
python -m nowcast.pipeline nowcast          # stima del trimestre in corso
python -m nowcast.pipeline select-factors   # evidenze sulla scelta dei fattori
pytest
```

I dati scaricati finiscono in `data/`, esclusa da git. Le API di Eurostat e BCE non richiedono chiavi.
