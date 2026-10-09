# Truth Social real-image OCR benchmark

This is an **offline, non-alerting benchmark** for the Trump public-account image-text detector, not a feed or a production scraper. The manifest was collected from the anonymous public account response on 2026-10-09. Images are **not** committed, and no authentication, cookies, CAPTCHA workarounds, or proxy rotation is used.

## Run on the Windows host

Use the normal, already-installed \`trade-alert\` Python environment:

\`\`\`powershell
Set-Location 'C:\ClaudeCode\trade-alert'
& .\.venv\Scripts\python.exe .\scripts\benchmark_truth_ocr.py --limit 50
\`\`\`

The test uses the existing allowlisted HTTPS image fetcher and four-pass local Tesseract OCR, waits at least 0.5 seconds between images, and aborts after three consecutive download failures. No historical post generates a Windows notification, nor are raw image bytes persisted. The default run considers only the first eligible media image per post, reproducing the current live scanner's restriction. To study missed second/third images separately:

\`\`\`powershell
& .\.venv\Scripts\python.exe .\scripts\benchmark_truth_ocr.py --all-media --limit 50
\`\`\`

The script saves a JSON report under \`%LOCALAPPDATA%\TradeAlert\OCR-Benchmarks\`, including URL, image content SHA-256, text output, priority, category, and failures. If the target of 50 **distinct image contents** cannot be reached, the process exits nonzero and reports the actual coverage; do not call it a 50-image validation.

**Limitations:** This is an *unlabelled* historical corpus. It measures mechanical success, timeouts, image-only classifier decisions and duplicate-content incidence, but it cannot estimate OCR accuracy, precision, recall, or false-negative rate without a manually checked ground truth. It is deliberately image-only; caption-plus-OCR performance is an additional test. Multiple attachments from one post can contain relevant text that the current live scanner never sees. Media URLs may stop resolving, and Truth Social's terms restrict unapproved automated collection; a reachable URL does not imply authorization for broad harvesting. Stop on access refusal and do not evade rate limits or access controls.

If the run succeeds, sample OCR-empty and IGNORE images for human review, add manual expected text/relevance labels, and use those to decide whether another OCR preprocessing pass is worthwhile. Do not tune the classifier against its own unverified predictions.
