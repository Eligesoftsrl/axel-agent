# AXEL · assistente personale

AXEL è il tuo assistente personale basato su Claude: un avatar umanoide 3D a particelle
(testa liscia, volto a V, fascia luminosa al posto degli occhi) che dialoga con un "cuore dati".
Gestisce **calendario Google, Gmail, Spotify, promemoria, briefing mattutino, ricerca web e una
memoria a lungo termine**, e puoi scrivergli anche da **Telegram**. Gira sul tuo Mac.

```
axel-agent/
├── backend/                FastAPI (porta 8010)
│   ├── app/main.py         endpoint REST + /api/chat (SSE) + avvio attività in background
│   ├── app/agent.py        loop agentico Claude (streaming, strumenti, prompt con data/memoria)
│   ├── app/tools.py        registro strumenti (memoria, storico, calendario, gmail, promemoria, meteo…)
│   ├── app/memory.py       ricordi + storico conversazioni + import chat di claude.ai (SQLite FTS5)
│   ├── app/google_api.py   OAuth Google, Calendar, Gmail
│   ├── app/actions.py      azioni che richiedono conferma (invio email, eventi)
│   ├── app/reminders.py    promemoria con ricorrenza
│   ├── app/scheduler.py    controllo promemoria + briefing mattutino
│   ├── app/telegram.py     bot Telegram (notifiche + chat)
│   ├── app/weather.py      meteo Open-Meteo (gratis, senza chiave)
│   ├── app/mac.py          controllo del Mac (app, file, PDF, Note, volume, schermo, Comandi rapidi)
│   ├── app/proactive.py    avvisi eventi, email importanti, riepilogo serale
│   ├── app/tasks.py        compiti ricorrenti eseguiti da AXEL
│   ├── app/hue.py          luci Philips Hue (API locale del Bridge)
│   ├── app/spotify.py      Spotify: in ascolto, play/pausa, ricerca, playlist, dispositivi
│   └── data/               database locale axel.db, agents.json, credenziali Google
└── frontend/               React 19 + Vite + three.js (porta 5173)
    ├── src/scene/          avatar, cuore dati, flusso dati, sfondo
    ├── src/ui/             Builder, Integrazioni, Cronologia, Lyrics (testo laterale), conferme, toast
    └── src/lib/            api, voce (TTS/STT), controller
```

## Avvio

```bash
# backend (Python 3.11+; con uv)
cd backend
uv venv --python 3.13 && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env            # compila ANTHROPIC_API_KEY (e TELEGRAM_BOT_TOKEN)
uvicorn app.main:app --reload --port 8010

# frontend (altro terminale)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

> Dopo aver modificato `.env` riavvia uvicorn (`Ctrl+C` e di nuovo): `--reload` non rilegge il file.

Poi apri **Integrazioni** nell'app per collegare Google e Telegram e attivare il briefing.

---

## Guida 1 · Telegram (5 minuti)

1. Su Telegram cerca **@BotFather** → `/newbot` → scegli un nome (es. *AXEL*) e uno username
   che finisca in `bot` (es. `axel_filippo_bot`).
2. BotFather ti dà un **token** tipo `123456:ABC-...`. Mettilo nel `.env`:
   `TELEGRAM_BOT_TOKEN=123456:ABC-...` e riavvia il backend.
3. In AXEL → **Integrazioni → Telegram** premi **Apri @tuobot** e poi **Avvia** su Telegram:
   il collegamento è automatico. Il bot risponde solo alla tua chat.

Da Telegram puoi scrivere ad AXEL come nell'app ("ricordami domani alle 9 di chiamare Marco",
"cosa ho in agenda giovedì?"), scrivere `/briefing` per riceverlo subito, e confermare le
azioni con i pulsanti ✅ / ✖.

## Guida 2 · Google Calendar e Gmail (15 minuti, una volta sola)

1. Vai su <https://console.cloud.google.com>, in alto scegli il progetto (o creane uno nuovo).
   Controlla di essere loggato con **l'account Google che vuoi collegare** (in alto a destra).
2. **API e servizi → Libreria**: abilita **Google Calendar API** e **Gmail API**.
3. **API e servizi → Schermata consenso OAuth** (o "Google Auth Platform"):
   - tipo utente **Esterno**, nome app *AXEL*, la tua email come supporto e contatto;
   - in **Utenti di test / Audience** aggiungi la tua email Gmail;
   - *consigliato*: porta lo stato su **In produzione**. In modalità "Test" Google fa scadere
     l'autorizzazione ogni 7 giorni. In produzione vedrai l'avviso "app non verificata":
     è normale per un'app personale, clicca *Avanzate → Vai ad AXEL*.
4. **API e servizi → Credenziali → Crea credenziali → ID client OAuth**:
   - tipo **Applicazione web**;
   - **URI di reindirizzamento autorizzati**: `http://localhost:8010/api/google/callback`
5. Scarica il JSON del client e salvalo come **`backend/data/google_client_secret.json`**.
6. In AXEL → **Integrazioni → Google → Collega Google**, scegli l'account e accetta.

Il token resta nel database locale sul tuo Mac. AXEL può leggere calendario ed email liberamente;
**invio email e creazione/eliminazione eventi partono solo dopo la tua conferma**.

## Guida 3 · Spotify (5 minuti)

1. Vai su <https://developer.spotify.com/dashboard>, accedi con il tuo account Spotify → **Create app**.
2. Nome *AXEL*, descrizione a piacere, **Redirect URI**: `http://127.0.0.1:8010/api/spotify/callback`
   (proprio `127.0.0.1`, Spotify non accetta `localhost`). Spunta **Web API** e salva.
3. In **Settings** copia *Client ID* e *Client secret* nel `.env`:
   `SPOTIFY_CLIENT_ID=...` e `SPOTIFY_CLIENT_SECRET=...`, poi riavvia il backend.
4. In AXEL → **Integrazioni → Spotify → Collega Spotify** e accetta.

Prova: *"metti la mia playlist Focus"*, *"metti qualcosa dei Daft Punk"*, *"abbassa al 30%"*,
*"cosa sto ascoltando?"*, *"sposta la musica sul telefono"*. Spotify deve essere aperto su almeno
un dispositivo. Il controllo della riproduzione richiede **Spotify Premium**. L'app resta in
"Development mode": va benissimo per uso personale.

**Se AXEL dice "serve Premium" ma sei Premium** (regole Spotify da febbraio 2026):
- deve essere **Premium anche l'account che ha creato l'app** su developer.spotify.com (se l'hai creata
  con un altro account, ad esempio quello di lavoro, crea l'app di nuovo con il tuo account Premium);
- il tuo account deve essere in **Settings → User Management** dell'app (nome + email Spotify, massimo 5 utenti);
- poi **Scollega** e **Collega** di nuovo Spotify in Integrazioni.
In **Integrazioni → Spotify → Diagnostica** AXEL controlla tutto passo passo e ti dice cosa non va.

## Guida 4 · Importare le chat di claude.ai

1. Su claude.ai: **Impostazioni → Privacy → Esporta dati**. Ti arriva un'email con un link allo `.zip`.
2. In AXEL → **Integrazioni → Chat di claude.ai → Carica export** e scegli lo zip.
3. Chiedi ad AXEL: *"cerca nelle mie chat di Claude cosa avevo deciso sul trasloco"*,
   *"fammi la lista delle cose da fare emerse nelle ultime chat"*.

Puoi ripetere l'import quando vuoi: le chat già presenti vengono saltate.


## Guida 5 · Controllo del Mac (permessi)

AXEL usa gli strumenti nativi di macOS. La prima volta che li usa, macOS chiede dei permessi
**all'app da cui avvii il backend** (Terminale, iTerm o VS Code): concedili.

| Funzione | Permesso (Impostazioni di Sistema → Privacy e sicurezza) |
|---|---|
| Note, Cestino del Finder | **Automazione** → consenti l'app su *Note* e *Finder* (compare un popup) |
| "guarda il mio schermo" | **Registrazione schermo e audio di sistema** → abilita l'app, poi riavviala |
| Cerca file (Spotlight), apri app, volume, appunti | nessuno |

Esempi: *"apri VS Code nel progetto axel-agent"*, *"trova il PDF del contratto d'affitto e riassumimelo"*,
*"aggiungi alle Note la lista della spesa: latte, pane, uova"*, *"volume al 30"*, *"guarda il mio schermo:
cosa non va in questo errore?"*, *"copia negli appunti la mail che mi hai scritto"*.

**Comandi rapidi**: AXEL può eseguire qualsiasi Comando rapido dell'app *Comandi*. Per "non disturbare",
crea un comando chiamato ad esempio *Non disturbare* con l'azione "Imposta full immersion" e dì
*"attiva non disturbare"*. Stessa cosa per luci, scene, automazioni di casa.
Luminosità: `brew install brightness` (facoltativo).

**Sicurezza**: lavora solo dentro la tua cartella Home; cestinare, spostare file e lanciare comandi da
terminale **richiedono sempre conferma** (scheda nell'app o pulsanti su Telegram).

## Guida 6 · Luci Philips Hue (1 minuto)

1. Il Mac deve essere sulla stessa rete Wi-Fi del Bridge Hue.
2. In AXEL → **Integrazioni → Luci Philips Hue**: premi il **pulsante rotondo sul Bridge**, poi entro 30 secondi
   **Collega Bridge Hue**. Il Bridge viene trovato da solo; se non succede, metti il suo IP in `HUE_BRIDGE_IP` nel `.env`
   (app Hue → Impostazioni → Bridge Hue → i).
3. Prova: *"accendi il soggiorno al 40%"*, *"spegni tutte le luci"*, *"luce calda in camera"*, *"metti la scena Rilassati"*,
   *"quali luci sono accese?"*. Funziona anche da Telegram e nei compiti ricorrenti
   (*"ogni sera alle 23:30 spegni tutte le luci"*).

## Widget meteo e parole personali

- Quando chiedi il meteo compare un **widget olografico** (temperatura, condizioni animate, umidità, vento,
  alba/tramonto, andamento delle prossime ore, 4 giorni) che svanisce da solo dopo ~45 secondi.
- Quando usi Spotify (*"cosa sta suonando?"*, *"metti…"*, *"pausa"*, *"prossimo"*) compare la **scheda Spotify**
  nello stesso stile: copertina che gira dentro gli anelli, equalizzatore, avanzamento e comandi
  precedente/play-pausa/successivo. Si aggiorna da sola ogni 5 s, resta aperta finché ci tieni sopra il mouse,
  e se c'è anche il meteo si sposta in basso a sinistra.
- Se Spotify è chiuso, AXEL **apre da solo l'app sul Mac** (in background) e fa partire il brano: basta dire
  *"Axel, fammi ascoltare We Will Rock You dei Queen"*. Serve Spotify Premium.
- **YouTube**: *"apri YouTube e cerca Maradona"* apre i risultati nel browser; *"metti su YouTube i gol di
  Maradona"* fa partire direttamente il primo video.
- **Parole da riconoscere** (Costruisci agente): elenca nomi propri, aziende, luoghi (es. *Perfexia*). Il
  riconoscimento vocale li storpia spesso: AXEL corregge la trascrizione e usa il nome giusto nelle ricerche.

## Guida 7 · Voce locale con Whisper (consigliata, 5 minuti)

Con Whisper il riconoscimento vocale gira sul tuo Mac: è molto più preciso (anche su nomi come *Perfexia*),
non confonde la voce di AXEL con la tua (microfono con cancellazione dell'eco + rilevatore di voce) e
nessun audio va a Google.

```bash
cd backend
uv pip install -r requirements-voice.txt    # su Mac con chip Apple installa mlx-whisper
```
Riavvia il backend, apri **Integrazioni → Voce e velocità** e premi **Prepara il modello Whisper**: la
prima volta scarica il modello (circa 1,5 GB per *large-v3-turbo* su chip Apple, circa 0,5 GB per *small*
sugli altri), poi resta in cache. Da quel momento le **mani libere** usano Whisper in automatico; se
Whisper non è installato o si blocca, AXEL torna da solo al riconoscimento del browser.
Opzioni nel `.env`: `WHISPER_MODEL=small|medium|large-v3-turbo`, `WHISPER_ENGINE=mlx|faster`.

## Guida 8 · Collegamenti MCP (Notion, GitHub, file, database…)

MCP è lo standard con cui i servizi offrono "strumenti" agli assistenti AI. AXEL può usare qualsiasi server
MCP: aggiungilo e i suoi strumenti diventano strumenti di AXEL, senza scrivere codice.

1. Aggiorna le dipendenze del backend: `uv pip install -r requirements.txt` (aggiunge il pacchetto `mcp`).
   Per i server con `npx` serve Node.js (c'è già se usi il frontend); per quelli con `uvx` serve `uv`.
2. **Integrazioni → Account → Collegamenti MCP** → scegli un modello: ti chiede solo ciò che serve
   (la cartella, il token, i dati del database); comando e variabili si compilano da soli e restano visibili
   in "Opzioni avanzate". I modelli:
   - **File di una cartella**: AXEL legge e cerca i file della cartella indicata (cambia `~/Documents` se vuoi).
   - **Pagine web**: legge il contenuto di una pagina dato il link.
   - **GitHub** (remoto): crea un *Personal access token* su github.com → Settings → Developer settings e
     sostituisci `IL_TUO_TOKEN`.
   - **Notion**: su notion.so/profile/integrations crea un'integrazione interna, copia il token (`ntn_…`) e
     **condividi** con l'integrazione le pagine che AXEL deve vedere (menu ··· della pagina → Connessioni).
   - **Database Postgres (sola lettura)**: metti la stringa di connessione in `DATABASE_URI`.
   - **Personalizzato**: qualsiasi server MCP, come comando locale o URL remoto (stesso formato di Claude Desktop).
3. Premi **Salva e collega**: il pallino diventa verde e vedi l'elenco degli strumenti.

**Conferme**: per ogni collegamento scegli *Conferma le modifiche* (predefinito: gli strumenti di sola lettura
partono subito, quelli che scrivono o cancellano chiedono il tuo OK come per le email), *Conferma sempre* o
*Nessuna conferma* (solo per server di cui ti fidi).

**Ricerca degli strumenti**: se i collegamenti offrono molti strumenti (oltre 20), AXEL passa a Claude solo
quelli pertinenti alla richiesta, più uno strumento `find_tools` per cercarne altri al volo. Così resta veloce.

La configurazione è in `backend/data/mcp.json` (token compresi, solo sul tuo Mac); i messaggi dei server locali
finiscono in `backend/data/mcp-logs/`. I server remoti che richiedono il login con OAuth non sono ancora
supportati: usa quelli con token.

## Guida 9 · Le nuove capacità

**Note vocali su Telegram.** Mandi un vocale al bot: Whisper lo trascrive (ti mostra cosa ha capito) e AXEL
risponde per iscritto e anche a voce, con la voce italiana del Mac. Serve la voce locale (Guida 7) con il
pacchetto `av` (già in `requirements-voice.txt`). Risposte vocali on/off da Integrazioni → Telegram o
scrivendo `/voce` al bot. Voce migliore: Impostazioni di Sistema → Accessibilità → Contenuti letti →
Voce di sistema → scarica una voce italiana "Premium" (es. Luca); oppure `MAC_VOICE=Luca` nel `.env`.
Al bot puoi mandare anche **PDF, Excel e foto**, con una didascalia come richiesta.

**Documenti e analisi.** Trascina un file sulla finestra di AXEL (o usa la graffetta): PDF, Excel, CSV, Word,
immagini. I PDF e le immagini li legge e li vede; con Excel e CSV scrive ed esegue codice Python (code
execution di Anthropic) per calcoli, confronti e grafici. I grafici compaiono come proiezione davanti ad
AXEL, con il pulsante per scaricarli. Esempi: *"confronta questi 3 preventivi e dimmi il più conveniente"*,
*"fammi il grafico delle vendite per mese"*.

**Programmatic tool calling.** Per le richieste con tanti passaggi (*"com'è la mia giornata: agenda, email
importanti, meteo e quanto ci metto ad arrivare dal primo cliente?"*) Claude può scrivere un piccolo
programma che chiama più strumenti di lettura in serie, invece di un giro per ciascuno: meno attese e meno
token. È automatico con il modello principale; le azioni che modificano qualcosa restano escluse e chiedono
sempre conferma. Si disattiva con `ANTHROPIC_CODE_EXECUTION=0` nel `.env`.

**Compiti in background.** *"Axel, cercami con calma un volo Napoli–Lisbona a novembre sotto i 200 euro"*,
*"confronta i preventivi che ho ricevuto questa settimana"*: parte un sotto-agente con più passaggi a
disposizione; tu continui a parlare con AXEL. Quando ha finito arriva una bolla dal cuore ("compito
completato") e il risultato completo su Telegram. Elenco e risultati in Integrazioni → Compiti in background.

**Spedizioni.** AXEL legge le email di negozi e corrieri (Amazon, BRT, GLS, SDA, Poste, DHL, UPS…) e tiene la
lista dei pacchi: avvisa quando un pacco è spedito, in consegna oggi, consegnato o ha un problema. *"Quando
arriva il pacco di Amazon?"*. Lista con link di tracciamento in Integrazioni → Spedizioni.

**Notizie su misura.** In Integrazioni → Notizie scegli le fonti (ANSA, Il Post, Wired, Hacker News… o
qualsiasi feed RSS) e scrivi i tuoi interessi: nel briefing del mattino arrivano le 5 notizie più
rilevanti per te, riassunte in una riga con il link. Anche a richiesta: *"novità sull'intelligenza artificiale?"*.

**Mappe e traffico.** In Integrazioni → Mappe imposta casa e ufficio. *"Quanto ci metto ad andare da Rossi in
via Roma 10 a Caserta?"*, *"a che ora devo partire per arrivare in ufficio alle 9?"*. Avviso **"parti ora"**
prima degli appuntamenti del calendario che hanno un indirizzo, calcolato con il traffico. Senza chiave usa
OpenStreetMap (gratis, senza traffico). Per il **traffico reale**: su console.cloud.google.com (lo stesso
progetto di Gmail) abilita **Routes API** e **Geocoding API**, crea una *chiave API* (Credenziali → Crea
credenziali → Chiave API, limitala a queste due API) e mettila in `GOOGLE_MAPS_API_KEY` nel `.env`.
Google chiede un account di fatturazione, ma l'uso personale rientra di solito nella quota gratuita mensile.

**Memoria che impara da sola.** Ogni sera (23:30, modificabile) AXEL rilegge le conversazioni del giorno e
salva fatti, preferenze, persone, clienti e decisioni; aggiorna i ricordi superati; se qualcosa è ambiguo te
lo chiede invece di salvarlo. Non salva dati sensibili. Puoi farlo subito da Integrazioni → Memoria che
impara. Le conversazioni lunghe nell'app vengono **compattate**: la parte vecchia diventa un riassunto,
così AXEL resta veloce senza perdere il filo.

## Guida 10 · Voce maschile di AXEL (Google Cloud, senza ElevenLabs)

Le voci "Google" del browser per l'italiano sono solo femminili. Le voci maschili neurali di Google sono nel
servizio **Cloud Text-to-Speech**, che ha una quota gratuita mensile (1 milione di caratteri con le voci
Chirp 3 HD, 4 milioni con le WaveNet: per AXEL sono migliaia di risposte al mese).

1. Su <https://console.cloud.google.com> apri lo stesso progetto di Gmail → **API e servizi → Libreria** →
   cerca **Cloud Text-to-Speech API** → *Abilita*.
2. **API e servizi → Credenziali → Crea credenziali → Chiave API**. Modifica la chiave → *Limita chiave* →
   seleziona *Cloud Text-to-Speech API* (e se vuoi anche *Routes API* e *Geocoding API* per le Mappe).
3. Nel `.env`: `GOOGLE_TTS_API_KEY=la_tua_chiave` (se usi la stessa chiave delle Mappe basta
   `GOOGLE_MAPS_API_KEY`). Riavvia il backend.
4. In AXEL → **Costruisci agente → voce** compare il gruppo **Google Cloud · voci neurali**: le voci con ♂ sono
   maschili. Consigliate: **Chirp3-HD-Charon** (calda e profonda), **Chirp3-HD-Orus**, **Chirp3-HD-Fenrir**,
   oppure le Neural2/WaveNet maschili. Premi ▶ per provarle e salva.

La voce Google viene usata anche per i vocali su Telegram. Le frasi uguali (es. "Ok, mi fermo") restano in
cache e non consumano quota. Se la chiave manca o non funziona, AXEL te lo dice e continua con la voce del browser.

**Alternative gratuite**: le voci del Mac compaiono nello stesso menu (gruppo "Voci del Mac"); scarica
**Luca (Premium)** da Impostazioni di Sistema → Accessibilità → Contenuti letti → Voce di sistema → Gestisci
voci → Italiano. Oppure apri AXEL con **Microsoft Edge**: il menu voci del browser include le voci neurali
Microsoft maschili (es. "Diego" o "Giuseppe" Online, Natural).

## Guida 11 · Copia di sicurezza, email importanti, fonti di notizie

**Copia di sicurezza** (Integrazioni → Sistema). Ogni notte alle 3:30 AXEL salva in un file .zip memoria,
cronologia, promemoria, impostazioni, agenti e collegamenti MCP. Se il Mac era spento la fa appena si
riaccende. Cartella predefinita: **iCloud Drive/AXEL Backup** (così la copia sta anche fuori dal Mac), oppure
Documenti/AXEL Backup se iCloud Drive non è attivo; puoi sceglierne un'altra. Tiene le ultime 14 copie.
**Ripristina** riporta tutto a quel momento (prima salva comunque lo stato attuale). Le copie contengono gli
accessi a Google e Spotify: non condividerle. Non contengono `google_client_secret.json` (si riscarica da
Google Cloud) né gli allegati caricati.

**Email importanti** (Integrazioni → Routine). Come decide AXEL: prima le tue regole, poi Claude (modello
veloce) legge mittente, oggetto e anteprima delle email nuove e avvisa solo per persone reali, clienti,
scadenze, pagamenti e sicurezza. Puoi indicare:
- *mittenti prioritari* → avviso sempre (anche se Gmail li mette in Aggiornamenti o Promozioni): un indirizzo
  (`mario@cliente.it`), un intero dominio (`@perfexia.it`) o una parte del nome (`Commercialista`);
- *mittenti da ignorare* → mai avvisi;
- *cosa conta per te* in parole tue (es. "fatture e scadenze fiscali sì, conferme d'ordine no").

**Fonti di notizie** (Integrazioni → Info → Notizie). Incolla l'indirizzo di un feed RSS **o anche solo del
sito** (es. `ilmattino.it`): AXEL trova il feed, ne prende il nome e lo aggiunge come pulsante accanto ad
ANSA, Il Post… Tocca il pulsante per attivarlo/disattivarlo, la × per eliminarlo.

## Velocità e consumi

In **Integrazioni → Voce e velocità**:
- **Corsia veloce**: "spegni le luci", "luci della sala al 30%", "pausa", "prossima canzone", "volume al 40",
  "che ore sono" vengono eseguiti all'istante, senza passare da Claude. Frasi più articolate
  ("spegni le luci tra 10 minuti") vanno a Claude come sempre.
- **Modello automatico**: le richieste brevi e semplici le gestisce Haiku (più rapido ed economico), le
  altre il modello principale dell'agente.
- **Cache dei prompt** (sempre attiva): istruzioni e strumenti restano in cache tra un messaggio e l'altro.
- Il riquadro mostra le richieste di oggi, la percentuale letta dalla cache, i token e il tempo alla prima parola.

## Mani libere

Premi il pulsante con le onde accanto al volume (si illumina): da quel momento il microfono resta in
ascolto della parola **"Axel"**.
- *"Axel"* → si mette in ascolto; oppure tutto insieme: *"Axel, che tempo fa domani?"*
- **Conversazione continua**: se gli hai parlato a voce, dopo la risposta ascolta per ~6 secondi il seguito
  senza ripetere "Axel". Non lo fa dopo avvisi, notifiche o messaggi scritti.
- **Anti-eco e anti-rumore**: mentre parla non ascolta nulla; per 1,6 s dopo aver parlato scarta tutto; nel
  seguito ignora frasi di una parola (tranne *sì/no/ok/certo…*), trascrizioni incerte e pezzi delle sue ultime
  risposte. Se senti ancora falsi attivazioni, usa le cuffie o abbassa il volume del Mac.
- **Interruzione**: mentre parla dì solo *"stop"*, *"basta"*, *"fermati"* o *"aspetta"*.
Funziona con Chrome o Edge; la scelta resta salvata nel browser.

## Proattività

Da **Integrazioni → Proattività**:
- **Avvisi appuntamenti**: X minuti prima di ogni evento del calendario (con luogo e link Meet).
- **Email importanti**: ogni 5 minuti controlla le nuove email e un modello veloce di Claude
  (`TRIAGE_MODEL`, default Haiku) segnala solo quelle da persone reali, scadenze, pagamenti, sicurezza.
  Al primo avvio non segnala gli arretrati.
- **Suoni**: `frontend/public/sounds/wakeup.mp3` all'apertura, `notifica.mp3` per notifiche, bolle e widget (rispettano "silenzia"; sostituisci i file per cambiarli).
- **Bolle nuove email**: ogni N minuti (default 10, regolabile) AXEL controlla Gmail; per ogni email nuova il suo
  cuore si illumina e ne esce una bolla trasparente con mittente e oggetto (clic sull'icona = apri in Gmail,
  altoparlante = fattela leggere). "Prova bolla" in Integrazioni mostra l'animazione. Icona: busta olografica;
  se vuoi un'icona tua mettila in `frontend/public/mail-icon.svg`.
- **Riepilogo serale** all'ora scelta.
- **Compiti ricorrenti** dettati a voce: *"ogni venerdì alle 18 fammi il riepilogo della settimana e delle
  email a cui non ho risposto"*, *"ogni lunedì alle 8 dimmi le scadenze della settimana"*.

Tutto arriva su Telegram (o email) e, se l'app è aperta, AXEL lo dice anche a voce.

---

## Cosa sa fare AXEL

| Area | Esempi |
|---|---|
| Memoria | "ricordati che mia moglie si chiama Giulia" · "cosa sai dei miei progetti?" |
| Storico | "di cosa avevamo parlato la settimana scorsa?" · ricerca nelle chat di claude.ai |
| Calendario | "cosa ho domani?" · "fissami una call con Luca venerdì alle 15" (con conferma) |
| Gmail | "ho email importanti?" · "rispondi a Mario che ci sono" (bozza → conferma → invio) |
| Promemoria | "ricordami ogni lunedì alle 9 di mandare il report" → notifica su Telegram |
| Briefing | ogni mattina all'ora scelta: meteo, agenda, email, promemoria, notizie |
| Web | notizie e informazioni aggiornate |
| Mac | "apri VS Code nel progetto" · "riassumimi il PDF del contratto" · "guarda il mio schermo" |
| Proattività | avvisi prima degli eventi · email importanti · compiti ricorrenti · riepilogo serale |
| Luci Hue | "accendi il soggiorno al 40%" · "luci viola in camera" · "scena Rilassati" |
| Spotify | "metti la mia playlist Focus" · "pausa" · "brano successivo" · "volume al 40" |

I ricordi si vedono e si cancellano da **Integrazioni → Memoria**. AXEL salva da solo le
informazioni durature che emergono nelle conversazioni.

**Notifiche**: Telegram se collegato, altrimenti email a te stesso (se Google è collegato), e
sempre un avviso nell'app aperta (AXEL lo legge anche ad alta voce). Promemoria e briefing
funzionano finché il Mac è acceso e il backend è avviato; se il Mac era spento all'ora del
briefing, viene recuperato entro 4 ore.

## Interfaccia

- **Testo laterale**: la risposta scorre accanto ad AXEL in stile *lyrics*; la parola pronunciata
  si illumina, le righe passate sfumano e tutto scompare a fine risposta.
- **Scenario**: AXEL al centro con il suo *pensiero* (il cuore dati) sospeso sopra la testa, anelli
  orbitanti e un raggio di luce verticale; ai lati grattacieli vettoriali a linee sottili, colline a
  linea sull'orizzonte, archi e nebulosa di punti nel cielo, pavimento a griglia che scorre
  (`src/scene/Skyline.tsx`, `City.tsx`). Quando AXEL elabora alza lo sguardo verso il pensiero.
- **Stati dell'avatar**: in attesa (respira, segue il mouse) · ascolto · elaborazione (gira la testa
  verso il cuore dati) · trasmissione (la fascia pulsa con la voce).
- `?view=close` / `?view=close-side` nell'URL: inquadratura ravvicinata del volto.

## Personalizzare

- **Nuovo strumento**: funzione in `tools.py` (riceve `ctx` + argomenti) → aggiungila a `REGISTRY`
  e ad `AVAILABLE`. Per azioni con effetti esterni usa `_confirm(...)` e registra l'esecutore in
  `actions.EXECUTORS`.
- **Volto**: `headVisor()` in `src/scene/humanoidGeometry.ts`.
- **Voce maschile realistica**: TTS lato server (ElevenLabs / OpenAI / Azure) → riproduzione con
  Web Audio → `AnalyserNode` su `live.levelTarget` e avanzamento su `live.spoken`.

## Sicurezza

Il backend ascolta solo su `127.0.0.1`: è raggiungibile solo dal tuo Mac. Le chiavi stanno in
`.env` e in `backend/data/` (entrambi esclusi da git). Prima di esporlo in rete serve un login.
