# Provider connection guide

- Ollama: install and run `ollama serve`; pull `gemma:2b`; use base URL `http://localhost:11434/v1`.
- OpenAI: set `OPENAI_API_KEY` on the server, create a provider with type `openai`. A ChatGPT subscription is not API credit.
- Anthropic: set `ANTHROPIC_API_KEY`.
- OpenRouter: set `OPENROUTER_API_KEY`; pricing is model-specific.
- Gemini: set `GEMINI_API_KEY`.
- Custom endpoints: choose `custom_openai` or `vllm`, enter base URL, model ID, and optional API key env.
- Costs are `None`/unknown unless per-million pricing is configured.