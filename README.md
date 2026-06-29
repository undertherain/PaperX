# PaperX

Telegram redelivery demo built with Codex and OpenAI Agents SDK.

## Run

```bash
python3 -m pip install -r requirements.txt
playwright install chromium
export OPENAI_API_KEY="..."
export TELEGRAM_TOKEN="..."
python3 telegram_bot.py
```

Send the bot a redelivery slip photo, then reply with a natural time request like:

```text
around six pm
```

The Telegram flow now uses an Agents SDK planning agent to read the slip and match the requested time, asks for confirmation, then uses a confirmed booking agent to run the Playwright automation.

For the same-day driver-call branch, also run the voice bridge from the reference project in another terminal. Use Python 3.10-3.12 for that service because its Twilio audio path uses `audioop`.

```bash
cd /home/blackbird/Project_heavy/callout-openai-agent-sdk
python -m venv .venv
. .venv/bin/activate
pip install -e .
export OPENAI_API_KEY="..."
export TWILIO_ACCOUNT_SID="..."
export TWILIO_AUTH_TOKEN="..."
export TWILIO_FROM_NUMBER="..."
export PUBLIC_BASE_URL="https://your-public-host.example"
export VOICE_AGENT_INSTRUCTIONS="あなたは日本語の電話代行です。必ず短く、一文ずつ話します。雑談や説明はしません。目的を達成したらすぐ終了します。"
onestop-voice-agent serve --host 0.0.0.0 --port 8080
```

Optional PaperX settings:

```bash
export VOICE_AGENT_SERVER_URL="https://your-public-host.example"
export DRIVER_PHONE_NUMBER="+819012345678"
```

If `VOICE_AGENT_SERVER_URL` is not set, PaperX uses `PUBLIC_BASE_URL` for the voice bridge.
`DRIVER_PHONE_NUMBER` is useful for demos when the slip does not show a callable driver/depot number.

## Local agent check

```bash
python3 redelivery_agent.py downloads/AgACAgUAAxkBAAIBOWpCJjw14uW1qja_iA7-bQud4efhAAIsEmsbkmsRVigFmNv82-8EAQADAgADeQADPAQ.jpg "around six pm"
```

Add `--book` to run the browser booking automation.

To plan the same-day driver call:

```bash
python3 redelivery_agent.py downloads/AgACAgUAAxkBAAIBOWpCJjw14uW1qja_iA7-bQud4efhAAIsEmsbkmsRVigFmNv82-8EAQADAgADeQADPAQ.jpg --call-driver
```

Add `--call` to start the Twilio/OpenAI realtime voice call.
