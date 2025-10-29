# LLM Code Review (Gitea)

Run an LLM-based code review on pull requests and post the review as a comment to a Gitea instance. This action computes the PR diff, chunks it, calls your local or remote Ollama model, and publishes the results to the corresponding Gitea PR thread.

## Quick Start

Add a workflow like the following:

```yaml
name: LLM Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run LLM Code Review
        uses: ./
        with:
          gitea_base_url: https://gitea.example.com
          gitea_token: ${{ secrets.GITEA_TOKEN }}
          ollama_host: http://127.0.0.1:11434
          ollama_model: qwen2.5-coder:7b
          temperature: '0.2'
          max_context_chars: '20000'
          system_prompt: ''
```

Inputs:
- `gitea_base_url` (required): Base URL of the Gitea instance.
- `gitea_token` (required): Personal access token that can comment on PRs.
- `ollama_host` (required): Ollama API base, e.g. `http://127.0.0.1:11434`.
- `ollama_model` (required): Model name, e.g. `llama3.1:8b` or `qwen2.5-coder:7b`.
- `temperature` (optional, default `0.2`)
- `max_context_chars` (optional, default `20000`)
- `system_prompt` (optional): Custom system prompt override.

Notes:
- The action expects to run on `pull_request` events. It uses `GITHUB_EVENT_PATH` and `GITHUB_REPOSITORY` to read PR context and compute diffs.
