# Qimo Catcher

Local Chrome extension for Qimo Review Agent.

## Install

1. Open `chrome://extensions/`.
2. Enable Developer mode.
3. Click "Load unpacked".
4. Select `D:\QIMO_AGENT_TEST\browser-extension\qimo-catcher`.

## Use

1. Start the local service at `http://127.0.0.1:8000`.
2. Log in to the course site in Chrome.
3. Open the course video and play it for a few seconds.
4. Click the Qimo Catcher extension icon.
5. Click "Upload first in browser" first. This downloads with the logged-in browser session and uploads the file to the local service.
6. If browser upload fails, click "Import URLs" as fallback.

The extension sends data only to `127.0.0.1:8000`.
