# Trade Alert

Trade Alert är en liten lokal Windows tray-app för **latenskänslig nyhetsbevakning av en aktiv trade**.
Den ligger i notification area bredvid klockan, skickar Windows-notiser och kan inte lägga, ändra eller ta bort ordrar.

## Varför eget repo?

Trade Spine är kontrollplan och durable state. Trade Alert har en annan livscykel: den kör kontinuerligt,
pollar/streamar nyheter tätt och visar lokala notifieringar. Att hålla den separat minskar beroenden och
hindrar UI/Windows-fel från att påverka Trade Spine.

```text
DTV News Flow (primär, när watchlist-id är satt)
               \
                -> Trade Alert -> dedupe/relevans -> Windows toast
               /
Official TradingView via Trade Spine intelligence_state (fallback/komplettering)
```

### Gränser

- **Trade Spine:** portfölj, teser, verifierade underliggande, beslut och Official TradingView OAuth.
- **Trade Alert:** pollingintervall, kortlivad source cursor, headline-dedupe och notifieringar.
- **Ingen execution:** Trade Alert har inga broker-write-verktyg.

## Nuvarande oil-profil

Standardprofilen heter `BULL OLJA X16 AVA 2 / Brent` och använder `ICEEUR:BRN1!` för Official TradingView
News. Den symbolen är verifierad mot TradingViews nyhetsfeed för Brent och ska inte ersättas av en gissad
alias-symbol. Profilnamnet kan ändras lokalt i `config.json` utan att ändra source-routing.

DTV News Flow är avsedd som primär snabb feed, men dess verktyg kräver ett numeriskt TradingView-watchlist-ID.
Om `dtv_watchlist_id` är `null` kör Trade Alert ändå via Official TradingView-fallbacken.

## Installation / test

Krav: Windows, Python 3.12 via `uv`, lokal Trade Spine HTTP-runtime på `127.0.0.1:8773`. MCP Python SDK är pinnad och testad via `pyproject.toml`.

För en ny lokal checkout:

```powershell
Set-Location C:\ClaudeCode
git clone https://github.com/LurigeLars/trade-alert.git
Set-Location .\trade-alert
```

Om katalogen redan finns men saknar `trade_alert\__main__.py`, byt namn på den gamla katalogen och klona om
i stället för att försöka köra en ofullständig ZIP-extraktion.

```powershell
cd C:\path\to\trade-alert
uv run --python 3.12 python -m unittest discover -s tests -p "test_*.py"
uv run --python 3.12 python -m trade_alert --test-notification
uv run --python 3.12 python -m trade_alert --once
```

Första körningen skapar `%LOCALAPPDATA%\TradeAlert\config.json` och `%LOCALAPPDATA%\TradeAlert\state.db`.
Gamla headlines baselinas på första körningen; endast mycket färska headlines kan notifiera direkt.

När engångstestet ser bra ut:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-startup.ps1
```

Installationen använder den inloggade användarens Windows Startup-mapp och kräver därför **inte**
administratörsrättigheter. Installern använder `uv venv` + `uv pip install` i `.venv` och lämnar
inga genererade dependency-filer i Git-checkouten, så Docker-MCP:s clean-repo-skydd kan förbli aktiverat. Startup-genvägen pekar direkt på `.venv\Scripts\pythonw.exe`, så normal
drift har **inget PowerShell- eller konsolfönster**. `install-windows-task.ps1` finns kvar som
kompatibilitetswrapper och anropar samma per-user-installer.

När appen körs syns Trade Alert i Windows notification area (ibland under pilen `^` om Windows inte
har pinnat ikonen). Menyn visar aktuell källstatus och har bland annat **Senaste alerts**,
**Vad bevakas?**, **Pausa/Återuppta**, **Testnotis**, **Öppna loggmapp** och **Avsluta Trade Alert**.

Riktiga alerts sparas lokalt i SQLite med unread-status. Om en toast missas ligger därför en persistent
röd badge kvar på tray-ikonen och tooltip/meny visar antalet olästa alerts. **Senaste alerts** visar de
senaste 10 signalerna med full rubrik, provider, källa, publiceringstid, relevanspoäng och länk när sådan
finns. Endast de alerts som faktiskt visas markeras lästa; en ny alert som kommer samtidigt behåller sin
unread-status.

**Vad bevakas?** visar den effektiva konfigurationen direkt i UI:t: profilnamn, Official TradingView-symboler,
DTV-status, pollingintervall, max headlines, alerttröskel och de deterministiska scoringreglerna. Det kräver
inte att användaren öppnar loggfilen.

Informationsfönstren för **Vad bevakas?** och **Senaste alerts** använder ett eget läsfönster i stället för
Windows MessageBox. Texten är markerbar, stöder **Ctrl+A/Ctrl+C**, har **Kopiera allt**, scrollbar och
Segoe UI-baserad typografi. Tray-menyn har även **Tema → Följ Windows / Ljust / Mörkt**. Standard är
`system`, vilket läser Windows `AppsUseLightTheme` varje gång ett informationsfönster öppnas. Ett explicit
ljus- eller mörkerläge sparas lokalt i `%LOCALAPPDATA%\TradeAlert\config.json`. Befintliga config-filer
utan `theme_mode` fortsätter automatiskt med systemläget.

**Testnotis** går genom samma notifieringsbackend som riktiga nyhetsalerts. Windows-notiser skickas via
`windows-toasts`, inte via en dold PowerShell-process. Om backend-anropet misslyckas visar tray-status
`Notisfel · se logg` och felet skrivs till `%LOCALAPPDATA%\TradeAlert\trade-alert.log`.

Ingen broker-write eller elevated process introduceras.

Avinstallation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows-startup.ps1
```

## Relevansfilter

V0.1 använder deterministisk headline-ranking, inte en LLM i hot path. Signal får poäng från bland annat:

- oil/crude/Brent/WTI/OPEC;
- Iran/Hormuz/Saudi/Russia/sanktioner/pipelines/tankers/inventories/produktion;
- TradingView `urgency=1`;
- explicit Brent-relaterad symbol i provider-payloaden.

Det gör notifieringsvägen snabb och reproducerbar. En senare version kan lägga till prisrespons och en
separat modellbedömning efter att själva headline-notisen redan har gått ut.

## Lokal state och privacy

Personlig konfiguration, source cursors och dedupe-databasen ligger utanför repot under
`%LOCALAPPDATA%\TradeAlert`. OAuth ligger fortsatt hos Trade Spine. Inga kontonummer, brokerdata eller tokens
ska committas.
