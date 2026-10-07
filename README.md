# Trade Alert

Trade Alert är en liten lokal Windows tray-app för **latenskänslig nyhetsbevakning av en aktiv trade**.
Den ligger i notification area bredvid klockan, skickar Windows-notiser och kan inte lägga, ändra eller ta bort ordrar.

## Varför eget repo?

Trade Spine är kontrollplan och durable state. Trade Alert har en annan livscykel: den kör kontinuerligt,
pollar/streamar nyheter tätt och visar lokala notifieringar. Att hålla den separat minskar beroenden och
hindrar UI/Windows-fel från att påverka Trade Spine.

```text
DTV TradingView News Flow (primär broad discovery, max 200)
               \
                -> Trade Alert -> deterministic oil relevance -> Windows toast
               /
Official TradingView symbol-news via Trade Spine (targeted corroboration/fallback)
```

### Gränser

- **Trade Spine:** portfölj, teser, verifierade underliggande, beslut och Official TradingView OAuth.
- **Trade Alert:** pollingintervall, kortlivad source cursor, headline-dedupe och notifieringar.
- **Ingen execution:** Trade Alert har inga broker-write-verktyg.

## Nuvarande oil-profil

Standardprofilen heter `Oil / Brent`.

**Primär discovery är TradingView Desktop News Flow**, i linje med Trade Spines källpolicy efter den
praktiska källutvärderingen. En kontrakt-/ticker-specifik Brent-feed kan vara glest taggad och används
därför inte som primär discovery. Official TradingView `ICEEUR:BRN1!` finns kvar som verifierad
**targeted corroboration/fallback**, inte som huvudflöde.

Om `dtv_watchlist_id` är `null` använder Trade Alert inte längre symbol-news som normal primärväg.
Den läser i stället den aktiva TradingView-watchlisten via `watchlist_get`, kräver minst ett verifierat
oljeankare (Brent/WTI/refined-product routing symbol), och sparar det upplösta numeriska ID:t endast
lokalt i SQLite. Därmed kan broad News Flow användas utan att ett användarspecifikt watchlist-ID
committas till repot. Ett explicit lokalt `dtv_watchlist_id` kan fortfarande pinna en bestämd lista.

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

**Vad bevakas?** visar den effektiva routingmodellen direkt i UI:t: DTV News Flow som primär broad discovery,
lokalt auto-pinnad watchlist när sådan har upplösts, Official TradingView som targeted corroboration,
separata polling/limit-värden och de deterministiska scoringreglerna. Det kräver inte att användaren
öppnar loggfilen.

Informationsfönstren för **Vad bevakas?** och **Senaste alerts** använder ett eget läsfönster i stället för
Windows MessageBox. Texten är markerbar, stöder **Ctrl+A/Ctrl+C**, har **Kopiera allt**, scrollbar och
Segoe UI-baserad typografi. På Windows konfigurerar processen **Per-Monitor DPI Awareness V2 innan någon UI
skapas**, med äldre DPI-API:er som fallback. Det förhindrar att Windows bitmap-skalar tray/Tk-innehåll på
hög-DPI-skärmar, vilket annars kan göra texten synligt suddig. Tray-menyn har även **Tema → Följ Windows / Ljust / Mörkt**. Standard är
`system`, vilket läser Windows `AppsUseLightTheme` för informationsfönstren och sätter Win32-menyn till
`AllowDark`. **Mörkt** använder native `ForceDark` och **Ljust** `ForceLight`; Windows menytema flushas
och pystray-menyn byggs om efter ändring. Därmed följer även själva högerklicksmenyn valt tema i stället för
att alltid vara ljus. Windows exponerar fortfarande den klassiska Win32 dark-menu-opt-in-ytan via privata
`uxtheme.dll`-ordinals, så implementationen resolvar dem dynamiskt och faller säkert tillbaka om de saknas.
Ett explicit ljus- eller mörkerläge sparas lokalt i `%LOCALAPPDATA%\TradeAlert\config.json`. Befintliga
config-filer utan `theme_mode` fortsätter automatiskt med systemläget.

**Testnotis** går genom samma notifieringsbackend som riktiga nyhetsalerts. Windows-notiser skickas via
`windows-toasts`, inte via en dold PowerShell-process. Om backend-anropet misslyckas visar tray-status
`Notisfel · se logg` och felet skrivs till `%LOCALAPPDATA%\TradeAlert\trade-alert.log`.

Ingen broker-write eller elevated process introduceras.

Avinstallation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-windows-startup.ps1
```

## Relevansfilter

Broad News Flow kräver hårdare routing än symbol-news. V0.1 använder därför deterministisk ranking utan
LLM i hot path:

- explicit olje/core-term i rubriken ger +2;
- impact-termer som Iran/Hormuz/supply/tanker ger +2 **endast när oljecontext redan finns**;
- en provider-relaterad Brent/WTI/refined-product-symbol ger +1 som routing evidence;
- `urgency=1` ger +1 endast i oljecontext;
- en relaterad symbol ensam kan aldrig nå alerttröskeln.

Det förhindrar att generiska broad-feed-rubriker med ord som `deal` eller `increase` blir falska
oljealerts, samtidigt som exempelvis en Iran/Hormuz-rubrik med olje-routing kan passera även om ordet
`oil` saknas i själva rubriken.

Första gången broad News Flow aktiveras baselinas gamla artiklar; bara mycket färska artiklar får notifiera
direkt. Därefter används source cursor och headline-dedupe.

## Lokal state och privacy

Personlig konfiguration, source cursors och dedupe-databasen ligger utanför repot under
`%LOCALAPPDATA%\TradeAlert`. OAuth ligger fortsatt hos Trade Spine. Inga kontonummer, brokerdata eller tokens
ska committas.
