# Trade Alert

Trade Alert är en liten lokal Windows-worker för **latenskänslig nyhetsbevakning av en aktiv trade**.
Den skickar Windows-notiser men kan inte lägga, ändra eller ta bort ordrar.

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

Standardprofilen använder `ICEEUR:BRN1!` för Official TradingView News. Den symbolen är verifierad mot
TradingViews nyhetsfeed för Brent och ska inte ersättas av en gissad alias-symbol.

DTV News Flow är avsedd som primär snabb feed, men dess verktyg kräver ett numeriskt TradingView-watchlist-ID.
Om `dtv_watchlist_id` är `null` kör Trade Alert ändå via Official TradingView-fallbacken.

## Installation / test

Krav: Windows, Python 3.12 via `uv`, lokal Trade Spine HTTP-runtime på `127.0.0.1:8773`.

```powershell
cd C:\path\to\trade-alert
uv run --python 3.12 --with mcp==2.2.0 python -m unittest discover -s tests -p "test_*.py"
uv run --python 3.12 --with mcp==2.2.0 python -m trade_alert --test-notification
uv run --python 3.12 --with mcp==2.2.0 python -m trade_alert --once
```

Första körningen skapar `%LOCALAPPDATA%\TradeAlert\config.json` och `%LOCALAPPDATA%\TradeAlert\state.db`.
Gamla headlines baselinas på första körningen; endast mycket färska headlines kan notifiera direkt.

När engångstestet ser bra ut:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows-task.ps1
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
