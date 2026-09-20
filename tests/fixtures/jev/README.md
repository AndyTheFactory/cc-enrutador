# Synthetic OpenRouter Decisions fixtures

These fixtures model the documented OpenRouter `POST /api/alpha/decisions`
response envelope (`answers.task_tier`, `model`, optional `usage`).
They are synthetic, not captured from a real account or conversation.

Reference: https://openrouter.ai/labs/jev/compile and
https://github.com/OpenRouterTeam/ai-sdk-provider

Use `httpx.MockTransport` to exercise the request and HTTP error categories.
No API key, Claude subscription token, or private task content is included.
