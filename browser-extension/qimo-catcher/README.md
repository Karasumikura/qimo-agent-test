# Qimo Catcher

Local Chrome extension for the Qimo Review Agent.

## Install

1. Start the local service at `http://127.0.0.1:8000`.
2. Open `chrome://extensions/`.
3. Turn on Developer mode.
4. Click "Load unpacked".
5. Select `D:\QIMO_AGENT_TEST\browser-extension\qimo-catcher`.

## Normal use

1. Log in to JLU Learning in Chrome.
2. Open the target course video.
3. Play the video for a few seconds.
4. Leave the rest to the extension and the local dashboard.

The extension runs in automatic mode by default. It watches authorized media
requests, extracts page transcripts when available, and sends them only to
`127.0.0.1:8000`.

The popup is a status panel. Use it only to pause Auto, retry the current tab,
open the dashboard, or clear local import history.

## Boundaries

The extension does not read passwords or export browser cookies. It does not
bypass CAPTCHA, DRM, or access controls. It only works with requests that your
normal logged-in browser session can already access.
