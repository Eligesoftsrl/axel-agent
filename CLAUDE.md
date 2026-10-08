# AXEL · contesto del progetto per Claude

Questo file è il "passaggio di consegne": leggilo prima di lavorare sul repository.
Ultimo aggiornamento: 8 ottobre 2026.

## Chi e cosa

- **Utente**: Filippo Malafronte (Eligesoft srl), sviluppatore, Napoli. Scrive in **italiano** (spesso veloce, con
  refusi): rispondi sempre in italiano, chiaro e concreto. Conosce git.
- **AXEL** è il suo assistente personale: interfaccia 3D olografica nel browser + backend Python che usa Claude.
  Gira **solo sul suo Mac** (Apple Silicon, macOS recente, uv + Python 3.13, Node). Progetto in `~/React/axel-agent`.
- Repository: `Eligesoftsrl/axel-agent` (privato). **Flusso di lavoro**: Claude modifica, fa commit e push su `main`;
  Filippo fa `git pull` e riavvia il backend. Dopo ogni push digli in breve cosa è cambiato e se servono
  `uv pip install -r requirements.txt` / `npm install`. Messaggi di commit in italiano.

## Avvio (sul Mac)

```bash
cd backend && uv venv && source .venv/bin/activate
uv pip install -r requirements.txt -r requirements-voice.txt
uvicorn app.main:app --port 8010          # porta 8010: la 8000 è occupata da Docker (IPv6)
cd frontend && npm install && npm run dev  # http://localhost:5173 (proxy /api → http://127.0.0.1:8010)
```
Segreti in `backend/.env` (vedi `.env.example`) e in `backend/data/` (DB, token, `google_client_secret.json`,
`mcp.json`, copie di sicurezza): **mai nel repository**, già esclusi da `.gitignore`.

## Architettura

**Frontend** (`frontend/`): React 19 + Vite + TypeScript, zustand (`store.ts`, più l'oggetto `live` per i valori per-frame),
@react-three/fiber + drei + postprocessing.
- `scene/`: umanoide di particelle (shader GLSL, `uReveal` = materializzazione: usato anche per dissolverlo quando la
  galleria è aperta), visiera a V, cuore dati, skyline, plexus. Non riprodurre personaggi esistenti (Sentinel/Ultron):
  il design è originale.
- `lib/controller.ts`: orchestratore (invio messaggi, eventi SSE, notifiche ogni 15 s, comandi galleria).
- `lib/voice.ts`: Speaker (voci browser, oppure `google:`/`mac:` dal backend con bocca sincronizzata su AnalyserNode).
- `lib/handsfree.ts` + `lib/whisper.ts`: mani libere con parola "Axel"; motore Whisper locale (VAD Silero nel
  browser → `/api/stt`) con il riconoscitore del browser usato solo per mostrare le parole live; anti-eco
  (finestra sorda 1,6 s, confronto con le ultime risposte, seguito solo dopo un turno vocale, "stop" solo se breve).
- `ui/`: HUD olografici (meteo, Spotify, galleria Cover Flow, risultati analisi, bolle email/compiti dal cuore),
  pannello Integrazioni a 5 schede con card richiudibili (`Card.tsx`, `BusyLabel` per evitare salti di layout),
  Builder dell'agente (voce, persona, strumenti, vocabolario).

**Backend** (`backend/app/`): FastAPI su 127.0.0.1:8010, SSE per la chat, SQLite (FTS5) in `data/axel.db`.
- `agent.py`: loop agentico con streaming, **prompt caching** (system statico in cache + parte dinamica, cache su
  strumenti e ultimo messaggio), **scelta modello** (Haiku per richieste brevi, `claude-sonnet-5-5` per il resto),
  **code execution** `code_execution_20260120` + **programmatic tool calling** (`allowed_callers` sugli strumenti in
  `tools.PTC_SAFE`), riuso del container, download dei file generati, strumenti MCP con `find_tools`.
- `fastlane.py`: comandi semplici senza Claude (luci, musica, volume, ora). `main.py` lo prova prima dell'agente.
- `tools.py`: REGISTRY degli strumenti per gruppo (memory, history, reminders, calendar, gmail, mac, hue, tasks,
  news, background, maps, shipments, mcp, spotify, weather, web_search…). `_confirm()` = azione in attesa di conferma.
- `actions.py`: azioni con effetti (email, eventi, cestino/sposta/comandi Mac, `mcp_call`) eseguite solo dopo conferma.
- Integrazioni: `google_api.py` (OAuth Calendar/Gmail), `spotify.py` (Premium, scelta del risultato migliore,
  `wait_state` dopo play), `hue.py`, `telegram.py` (chat, vocali con Whisper, documenti, risposte vocali),
  `mac.py` (solo dentro la Home), `weather.py` (Open-Meteo), `maps.py` (Google Routes con chiave, altrimenti OSM),
  `mcp_client.py` (server MCP stdio/HTTP da `data/mcp.json`, SDK `mcp` 2.x: campi snake_case).
- Funzioni di sfondo (`scheduler.py` ogni 20 s → `proactive.tick`): avvisi appuntamenti, email importanti (regole
  utente + triage Haiku), bolle email, spedizioni, "parti ora", riepilogo serale, compiti ricorrenti, memoria che
  impara (sera), copia di sicurezza notturna (`backup.py`, iCloud Drive/AXEL Backup).
- Altro: `stt.py` (Whisper: mlx-whisper su Apple Silicon, faster-whisper altrove; qualità veloce=small),
  `tts.py` (Google Cloud TTS o voci macOS `say`), `documents.py` (Files API, PDF/immagini/Excel), `background.py`
  (sotto-agente fino a 25 passi), `learning.py` (estrazione memoria + compattazione a blocchi di 10),
  `news.py` (RSS + interessi), `shipments.py`, `photos.py` (galleria, anteprime con sips/Pillow), `llm.py` (Haiku JSON).
- Migrazioni agenti: `store.py` `VERSION`/`NEW_TOOLS` (aggiungi lì i nuovi gruppi di strumenti).

## Regole da rispettare

- **Sicurezza**: backend solo su 127.0.0.1; file del Mac solo dentro la Home; azioni con effetti sempre con
  conferma (UI e Telegram); token e dati personali mai nel repo; copie di sicurezza e `mcp.json` con permessi 600.
- **Stile UI**: olografico, trasparente, ciano/blu (`--a`, `--b`), angoli `hb`, scansione `hud-scan`, animazioni
  `hudIn`/`hudOut`, font Quicksand + IBM Plex Mono. Compatto ed elegante; niente salti di layout.
- **Testi**: tutto in italiano (UI, messaggi d'errore, README). Errori spiegati in modo comprensibile.
- **Marchi**: niente loghi di terzi (es. busta generica per Gmail, niente logo Spotify).
- Prima di ogni push: `npx tsc -b` e `npm run build` nel frontend, import del backend
  (`python -c "import app.main"`), e dove possibile un test reale (Playwright con Chromium in `/opt/pw-browsers`).
- Aggiorna `README.md` (guide numerate in italiano) quando aggiungi una funzione.

## Cose imparate (non ripetere gli errori)

- Spotify: da feb. 2026 l'app sviluppatore richiede Premium per il proprietario; i 403 non sono sempre "Premium":
  usare `_friendly()` e la diagnostica. La ricerca va filtrata per nome (il primo risultato può essere sbagliato).
- Google TTS richiede fatturazione: Filippo **non vuole** servizi a pagamento → voce consigliata **Luca (macOS)**
  via `mac:`; in alternativa Microsoft Edge (voci neurali gratuite del browser). Niente ElevenLabs.
- Whisper: il modello grande rallentava tutto → default "Veloce" (small) e trascrizione solo se il riconoscitore
  live ha sentito "Axel" (o si è in conversazione).
- Il vocabolario personale (Builder) corregge nomi che il riconoscimento storpia (es. Perfexia, Iron Maiden).
- In headless alcune transizioni CSS non avanzano: per barre di avanzamento preferire aggiornamenti senza transition.

## Stato e prossimi passi

Roadmap e checklist di collaudo nel documento "AXEL · Roadmap" (claude.ai). Fatto: sprint 1 (caching, corsia veloce,
Whisper), sprint 2 (MCP), sprint 3 (vocali Telegram, documenti/code execution, PTC, compiti in background, spedizioni,
notizie, mappe, memoria che impara), voce maschile, pannello a schede, copia di sicurezza, regole email, fonti RSS
personalizzate, form MCP semplificato, galleria foto Cover Flow.

Idee in coda (da proporre, non da fare senza richiesta):
1. **Foto di Apple** (libreria iCloud: album, luoghi, persone) per la galleria.
2. **Avvio automatico** del backend al login (launchd).
3. **Accesso dal telefono** con Tailscale.
4. **"Ehi Siri, chiedi ad Axel"** (Comando rapido).
5. **Scene e routine** (modalità cinema, buongiorno).
6. Modello MCP per MySQL/SQL Server se il gestionale di un cliente lo richiede.
