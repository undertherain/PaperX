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

## Local agent check

```bash
python3 redelivery_agent.py downloads/AgACAgUAAxkBAAIBOWpCJjw14uW1qja_iA7-bQud4efhAAIsEmsbkmsRVigFmNv82-8EAQADAgADeQADPAQ.jpg "around six pm"
```

Add `--book` to run the browser booking automation.
