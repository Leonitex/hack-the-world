# Phone-only MVP runbook

This branch is designed to run from an Android phone using Termux + Ubuntu/proot or any Python 3.11+ environment.

## What it demonstrates

- Meta **Muse Spark Open** through the Baseten hackathon endpoint
- OpenAI-compatible function/tool calling
- Optional image input for multimodal context
- Evidence ledger
- Multiple competing hypotheses
- User-in-the-loop diagnostic tests
- Deterministic recommendation verification

The model proposes actions, but the diagnostic core owns authoritative state and rejects malformed or unsupported transitions.

## Setup

```bash
git clone -b work/phone-mvp https://github.com/Leonitex/hack-the-world.git
cd hack-the-world
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set the hackathon key locally. Never commit it:

```bash
export BASETEN_API_KEY='your-key-here'
```

The hackathon Baseten key requires this exact model slug:

```text
meta-models/muse-spark-open-1026
```

## Test

```bash
python -m unittest discover -s tests -v
```

## Run

```bash
python phone_app.py
```

Open `http://127.0.0.1:8000` in the phone browser.

Start with a text-only case to verify the model loop, then repeat with an image. A good demo case is a device that powers on but produces no display: the agent should form competing hypotheses, ask for a discriminating test, ingest the real result, update the hypotheses, and only then produce a verified recommendation.

## Security

The API key stays in the local environment variable and is never sent to the browser or stored in the repository. The demo server is intended for a single local user during the hackathon prototype stage.
