# Anonymous direct Trump post monitor

Trade Alert has a bounded, read-only path for checking the public account
statuses endpoint at Truth Social. The source is queried directly from the
Windows Trade Alert process; no paid cloud service is involved. The source is
not guaranteed to allow anonymous access from every network.

## Data source and limitations

- Public account: realDonaldTrump
- Account ID: 107780257626128497
- Fixed endpoint: https://truthsocial.com/api/v1/accounts/107780257626128497/statuses
- Library-free Python HTTPS/JSON GET; no sign-in, credentials, or cookies
- If anonymous access fails with HTTP 401/403, stop trying for one hour.
  HTTP 429 rate limiting pauses for 30 minutes. Other failures use exponential
  retry backoff up to 10 minutes. No proxy/IP rotation, CAPTCHA solutions,
  forged session tokens, alternative login route, or hidden browser access.
- The endpoint is an undocumented/unsupported public-access interface; it
  can change. The reader verifies the account ID, account name and public
  visibility on every post. Links are constructed from these verified fields,
  not accepted blindly from the data source.
- First successful nonempty response creates an initial baseline without
  a burst of stale alerts. Subsequent posts matching oil/geopolitics/monetary
  policy/trade trigger the normal Windows Trade Alert notification and unread
  history, while old posts and duplicates are ignored.
- HTML is converted to inert text, not executed. Image/video-only posts are
  counted as skipped for now; text extraction from media is out of scope.
- No new order placement, position evaluation or account access is added.
- The independent RSS archive remains fallback. When the direct monitor
  checked successfully recently, RSS still refreshes but does not duplicate
  the newly observed direct items.

## Operational settings

The example config includes:

    "truth_direct_enabled": true,
    "truth_direct_poll_seconds": 15,
    "truth_direct_max_age_seconds": 300

These are local application defaults. Trade Alert keeps the existing source
configuration in %LOCALAPPDATA%/TradeAlert/config.json, so settings can be
overridden locally. The direct API is not under our control.

## Test

After merging/restarting, run the following in Windows PowerShell:

    Set-Location 'C:\ClaudeCode\trade-alert'
    & .\.venv\Scripts\python.exe -m trade_alert --direct-once

The command reports a compact status with no raw posts. BASELINED or
COMPLETE means the endpoint returned a validated JSON list. FAILED 403/401
means the endpoint refused anonymous access: leave the RSS fallback in place.
A successful test is a point-in-time connectivity result, not proof of
15-second publication-to-alert latency.

Measure:
- source post UTC created_at
- first successful fetch time (local)
- Windows notification delivery request time
- TradingView/Reuters earliest corresponding headline time

## Rights and practical boundaries

Truth Social terms restrict unauthorized automation. The technical existence
of an anonymously readable endpoint does not constitute a licence. A
personal-use tool's precise legal and contractual risk in Sweden/EU is not
settled by these technical checks. This implementation avoids access-control
evasion, impersonation and excessive load; it does not certify compliance
with the site's terms. Disable the monitor in local config if needed.
