# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
# Install dependencies
pip install flask portkey-ai anthropic

# Run the web app (Flask)
python app.py
# Accessible at http://localhost:5000

# Run the CLI grader directly
python card_grader.py path/to/card.jpg "1986 Fleer Michael Jordan #57"
# Or interactively:
python card_grader.py
```

## Architecture

This project has two separate implementations of the same PSA card grading functionality:

- **`card_grader.py`** — CLI tool using the Anthropic SDK directly (`anthropic` package). Requires `ANTHROPIC_API_KEY` env var. Uses `claude-opus-4-6` with `thinking: {"type": "adaptive"}` and streams output to stdout.

- **`app.py`** — Flask web app using Portkey AI gateway (`portkey_ai` package) as a proxy to Claude. The API key and base URL are hardcoded (NYU AI gateway). Uses SSE (Server-Sent Events) to stream the grading report to the browser.

- **`templates/index.html`** — Single-page frontend. Handles file upload with drag-and-drop, sends `multipart/form-data` to `POST /grade`, and reads the SSE stream. After the stream completes, `extractGrade()` parses the PSA grade number from the response text via regex and color-codes the grade badge.

Both files share the same `PSA_GRADING_SYSTEM` prompt defining the grading rubric and output format. The web app's system prompt differs slightly (adds output structure numbering). If you update the grading criteria, update both.

## Key Details

- Max upload size: 16MB
- Accepted formats: JPG, PNG, WebP (CLI also accepts GIF)
- The `/grade` endpoint streams JSON-encoded SSE chunks: `{"text": "..."}` during generation, then `[DONE]` to signal completion, or `{"error": "..."}` on failure
