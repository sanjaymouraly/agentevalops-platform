"""Unified AI provider abstraction.

Adapters use documented HTTP APIs and keep provider-specific semantics
(headers, token accounting, model discovery) in separate classes. API keys are
read from server environment variables only and are never persisted by the
application. Costs are only reported when explicit pricing is configured;
otherwise they are ``None`` with an ``unknown`` provenance string.
"""
from __future__ import annotations

import os
import time

import httpx

from .security import redact


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, status_code: int | None = None):
        self.kind = kind
        self.status_code = status_code
        super().__init__(redact(message))


def _pricing(params: dict) -> tuple[float | None, float | None]:
    """Return (input, output) USD per 1M tokens.

    ``input_price_per_million`` / ``output_price_per_million`` are preferred;
    legacy ``price_per_1k`` is treated as a blended rate for both directions.
    """
    inp = params.get("input_price_per_million")
    out = params.get("output_price_per_million")
    if inp is None and params.get("price_per_1k") is not None:
        inp = out = float(params["price_per_1k"]) * 1000
    try:
        return (float(inp) if inp is not None else None, float(out) if out is not None else None)
    except (TypeError, ValueError):
        return (None, None)


def _cost(inp, out, params: dict, local: bool = False) -> tuple[float | None, str]:
    if local:
        return (0.0, "local inference (no API charge)")
    pin, pout = _pricing(params)
    if pin is None and pout is None:
        return (None, "unknown: pricing not configured")
    if inp is None and out is None:
        return (None, "unknown: provider did not report token usage")
    cost = ((inp or 0) * (pin or 0) + (out or 0) * (pout or 0)) / 1_000_000
    return (round(cost, 6), "configured pricing (USD per 1M input/output tokens)")


class BaseProvider:
    name = "base"
    requires_key = True
    local = False

    def chat(self, messages, model=None, **kw) -> dict:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        return []

    def test_connection(self) -> dict:
        try:
            models = self.list_models()
            return {"ok": True, "detail": f"Connected; {len(models)} model(s) discovered.", "models": models}
        except ProviderError as e:
            return {"ok": False, "detail": str(e), "models": [], "error_kind": e.kind}

    def info(self) -> dict:
        return {"name": self.name, "requires_key": self.requires_key, "local": self.local}


class MockProvider(BaseProvider):
    """Offline deterministic provider used to exercise the wiring only.

    It is clearly labelled ``mock``; its output is never presented as model
    inference or used to claim LLM capability.
    """

    name = "mock"
    requires_key = False
    local = True

    def chat(self, messages, model="mock-1", **kw):
        last = messages[-1]["content"] if messages else ""
        return {
            "text": f"[mock-provider] deterministic echo: {str(last)[:160]}",
            "input_tokens": max(1, len(str(last)) // 4),
            "output_tokens": 16,
            "estimated_cost_usd": 0.0,
            "cost_provenance": "mock: zero cost",
            "model": "mock-1",
            "provider": self.name,
        }

    def test_connection(self):
        return {"ok": True, "detail": "Mock provider always available offline.", "models": ["mock-1"]}

    def list_models(self):
        return ["mock-1"]


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI, OpenRouter, Ollama (/v1), vLLM, custom endpoints, Azure."""

    def __init__(self, base_url, api_key="", model="", name="custom_openai", params=None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.name = name
        self.params = params or {}
        self.requires_key = name in ("openai", "openrouter", "custom_openai", "vllm")
        self.local = name in ("ollama", "vllm")

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if self.name == "openrouter":
            h["HTTP-Referer"] = self.params.get("http_referer", "https://github.com/AgentEvalOps")
            h["X-Title"] = self.params.get("x_title", "AgentEvalOps")
        return h

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise ProviderError("config_error", "Base URL is required for this provider")
        return f"{self.base_url}{path}"

    def list_models(self):
        try:
            r = httpx.get(self._url("/models"), headers=self._headers(), timeout=10)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError("provider_failure", f"model discovery failed: {e}")
        if r.status_code == 401:
            raise ProviderError("auth_error", "401 from provider: check the API key", 401)
        if r.status_code >= 400:
            raise ProviderError("provider_failure", f"HTTP {r.status_code} during model discovery", r.status_code)
        try:
            return [m.get("id", "") for m in r.json().get("data", []) if m.get("id")][:100]
        except Exception as e:
            raise ProviderError("provider_failure", f"malformed model list: {e}")

    def chat(self, messages, model=None, retries=None, **kw):
        model = model or self.model
        if not model:
            raise ProviderError("config_error", "No model configured")
        if self.requires_key and not self.api_key:
            raise ProviderError("auth_error", f"No API key configured for {self.name}")
        retries = int(retries if retries is not None else self.params.get("max_retries", 2))
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.params.get("temperature", 0.0),
            "max_tokens": self.params.get("max_tokens", 1200),
        }
        if self.params.get("top_p") is not None:
            payload["top_p"] = self.params["top_p"]
        last_err = None
        for attempt in range(retries + 1):
            try:
                started = time.time()
                r = httpx.post(self._url("/chat/completions"), headers=self._headers(), json=payload,
                               timeout=float(self.params.get("timeout_sec", 90)))
                if r.status_code == 401 or r.status_code == 403:
                    raise ProviderError("auth_error", f"{r.status_code}: check the API key", r.status_code)
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = ProviderError(
                        "rate_limit" if r.status_code == 429 else "provider_failure",
                        f"HTTP {r.status_code} from provider", r.status_code,
                    )
                    if attempt < retries:
                        retry_after = r.headers.get("retry-after")
                        time.sleep(min(float(retry_after) if retry_after else 2 ** attempt, 10))
                    continue
                if r.status_code >= 400:
                    raise ProviderError("provider_failure", f"HTTP {r.status_code}: {r.text[:300]}", r.status_code)
                data = r.json()
                choices = data.get("choices") or []
                if not choices:
                    raise ProviderError("provider_failure", "Provider returned no choices")
                text = choices[0].get("message", {}).get("content")
                if text is None and choices[0].get("text") is not None:
                    text = choices[0]["text"]
                usage = data.get("usage") or {}
                inp = usage.get("prompt_tokens", usage.get("input_tokens"))
                out = usage.get("completion_tokens", usage.get("output_tokens"))
                cost, provenance = _cost(inp, out, self.params, local=self.local)
                return {
                    "text": text or "",
                    "input_tokens": inp,
                    "output_tokens": out,
                    "estimated_cost_usd": cost,
                    "cost_provenance": provenance,
                    "model": data.get("model", model),
                    "provider": self.name,
                    "latency_ms": round((time.time() - started) * 1000, 2),
                }
            except ProviderError:
                raise
            except Exception as e:
                last_err = ProviderError("provider_failure", str(e))
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 8))
        raise last_err or ProviderError("provider_failure", "chat failed")

    def test_connection(self):
        if self.requires_key and not self.api_key:
            return {"ok": False, "detail": f"No API key configured for {self.name}.", "models": [], "error_kind": "auth_error"}
        return super().test_connection()


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama's OpenAI-compatible endpoint, with /api/tags model discovery fallback."""

    def __init__(self, base_url="http://localhost:11434/v1", model="gemma:2b", params=None):
        super().__init__(base_url, "", model, "ollama", params)
        self.local = True
        self.requires_key = False

    def list_models(self):
        try:
            return super().list_models()
        except ProviderError:
            root = self.base_url.removesuffix("/v1")
            try:
                r = httpx.get(f"{root}/api/tags", timeout=5)
                r.raise_for_status()
                return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
            except Exception as e:
                raise ProviderError("provider_failure", f"Ollama is not reachable at {root}: {e}")

    def test_connection(self):
        res = super().test_connection()
        if res.get("ok"):
            res["detail"] = f"Ollama connected; {len(res.get('models', []))} local model(s)."
        return res


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, api_key="", model="claude-sonnet-4-5", base_url="https://api.anthropic.com", params=None):
        self.api_key, self.model = api_key, model
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.params = params or {}

    def _headers(self):
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

    def list_models(self):
        if not self.api_key:
            raise ProviderError("auth_error", "Anthropic API key not configured")
        r = httpx.get(f"{self.base_url}/v1/models", headers=self._headers(), timeout=10)
        if r.status_code == 401:
            raise ProviderError("auth_error", "401: invalid Anthropic key", 401)
        r.raise_for_status()
        return [m.get("id", "") for m in r.json().get("data", []) if m.get("id")]

    def chat(self, messages, model=None, **kw):
        if not self.api_key:
            raise ProviderError("auth_error", "Anthropic API key not configured")
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        user_messages = [m for m in messages if m.get("role") != "system"]
        payload = {
            "model": model or self.model,
            "max_tokens": int(self.params.get("max_tokens", 1200)),
            "temperature": self.params.get("temperature", 0.0),
            "messages": user_messages,
        }
        if system:
            payload["system"] = system
        started = time.time()
        r = httpx.post(f"{self.base_url}/v1/messages", headers=self._headers(), json=payload,
                       timeout=float(self.params.get("timeout_sec", 90)))
        if r.status_code in (401, 403):
            raise ProviderError("auth_error", f"{r.status_code}: invalid Anthropic key", r.status_code)
        if r.status_code == 429:
            raise ProviderError("rate_limit", "429: Anthropic rate limit", 429)
        if r.status_code >= 400:
            raise ProviderError("provider_failure", f"HTTP {r.status_code}: {r.text[:300]}", r.status_code)
        d = r.json()
        u = d.get("usage") or {}
        inp, out = u.get("input_tokens"), u.get("output_tokens")
        cost, provenance = _cost(inp, out, self.params)
        return {
            "text": "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"),
            "input_tokens": inp, "output_tokens": out, "estimated_cost_usd": cost,
            "cost_provenance": provenance, "model": d.get("model", model or self.model),
            "provider": self.name, "latency_ms": round((time.time() - started) * 1000, 2),
        }

    def test_connection(self):
        return super().test_connection()


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key="", model="gemini-2.0-flash", base_url="https://generativelanguage.googleapis.com/v1beta", params=None):
        self.api_key, self.model = api_key, model
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.params = params or {}

    def list_models(self):
        if not self.api_key:
            raise ProviderError("auth_error", "Gemini API key not configured")
        r = httpx.get(f"{self.base_url}/models", params={"key": self.api_key}, timeout=10)
        if r.status_code in (401, 403):
            raise ProviderError("auth_error", f"{r.status_code}: invalid Gemini key", r.status_code)
        r.raise_for_status()
        return [m.get("name", "").removeprefix("models/") for m in r.json().get("models", [])][:100]

    def chat(self, messages, model=None, **kw):
        if not self.api_key:
            raise ProviderError("auth_error", "Gemini API key not configured")
        model = (model or self.model).removeprefix("models/")
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        contents = [
            {"role": "user" if m.get("role") in ("user", "system") else "model",
             "parts": [{"text": m.get("content", "")}]}
            for m in messages if m.get("role") != "system"
        ]
        payload = {"contents": contents, "generationConfig": {
            "temperature": self.params.get("temperature", 0.0),
            "maxOutputTokens": int(self.params.get("max_tokens", 1200)),
        }}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        started = time.time()
        r = httpx.post(f"{self.base_url}/models/{model}:generateContent",
                       params={"key": self.api_key}, json=payload,
                       timeout=float(self.params.get("timeout_sec", 90)))
        if r.status_code in (401, 403):
            raise ProviderError("auth_error", f"{r.status_code}: invalid Gemini key", r.status_code)
        if r.status_code == 429:
            raise ProviderError("rate_limit", "429: Gemini rate limit", 429)
        if r.status_code >= 400:
            raise ProviderError("provider_failure", f"HTTP {r.status_code}: {r.text[:300]}", r.status_code)
        d = r.json()
        candidates = d.get("candidates") or []
        if not candidates:
            raise ProviderError("provider_failure", "Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        usage = d.get("usageMetadata") or {}
        inp, out = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
        cost, provenance = _cost(inp, out, self.params)
        return {
            "text": "".join(p.get("text", "") for p in parts),
            "input_tokens": inp, "output_tokens": out, "estimated_cost_usd": cost,
            "cost_provenance": provenance, "model": model, "provider": self.name,
            "latency_ms": round((time.time() - started) * 1000, 2),
        }

    def test_connection(self):
        return super().test_connection()


class AzureOpenAIProvider(OpenAICompatibleProvider):
    name = "azure_openai"

    def __init__(self, base_url="", api_key="", model="", params=None):
        super().__init__(base_url, api_key, model, "azure_openai", params)
        self.requires_key = True

    def _headers(self):
        return {"Content-Type": "application/json", "api-key": self.api_key}

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise ProviderError("config_error", "Azure base URL is required")
        deployment = self.model
        api_version = self.params.get("api_version", "2024-10-21")
        if path == "/chat/completions":
            return f"{self.base_url}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        return f"{self.base_url}{path}?api-version={api_version}"


PROVIDER_TYPES = ["mock", "openai", "anthropic", "openrouter", "gemini", "ollama", "vllm", "custom_openai", "azure_openai"]

PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY", "gemini": "GEMINI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY", "vllm": "VLLM_API_KEY",
    "custom_openai": "CUSTOM_OPENAI_API_KEY",
}


def build_provider(provider_type: str, base_url="", model="", api_key_env="", params=None):
    from .config import get_settings

    params = params or {}
    key = os.environ.get(api_key_env, "") if api_key_env else ""
    if not key:
        key = os.environ.get(PROVIDER_ENV.get(provider_type, ""), "")
    if provider_type == "mock":
        return MockProvider()
    if provider_type == "openai":
        return OpenAICompatibleProvider(base_url or "https://api.openai.com/v1", key, model, "openai", params)
    if provider_type == "openrouter":
        return OpenAICompatibleProvider(base_url or "https://openrouter.ai/api/v1", key, model, "openrouter", params)
    if provider_type == "ollama":
        return OllamaProvider(base_url or get_settings().ollama_base_url, model or "gemma:2b", params)
    if provider_type in ("vllm", "custom_openai"):
        return OpenAICompatibleProvider(base_url, key, model, provider_type, params)
    if provider_type == "anthropic":
        return AnthropicProvider(key, model or "claude-sonnet-4-5", base_url or "https://api.anthropic.com", params)
    if provider_type == "gemini":
        return GeminiProvider(key, model or "gemini-2.0-flash", base_url or "https://generativelanguage.googleapis.com/v1beta", params)
    if provider_type == "azure_openai":
        return AzureOpenAIProvider(base_url, key, model, params)
    raise ValueError(f"Unsupported provider type: {provider_type}")


def provider_catalog() -> list[dict]:
    return [
        {"type": "mock", "label": "Offline mock", "requires_key": False, "local": True,
         "base_url": "", "default_model": "mock-1", "env_var": "",
         "note": "Deterministic echo for wiring/tests. Never used as LLM evidence."},
        {"type": "openai", "label": "OpenAI API", "requires_key": True, "local": False,
         "base_url": "https://api.openai.com/v1", "default_model": "gpt-4.1-mini", "env_var": "OPENAI_API_KEY",
         "note": "Requires a separately billed OpenAI API key; a ChatGPT subscription is not API credit."},
        {"type": "anthropic", "label": "Anthropic Claude API", "requires_key": True, "local": False,
         "base_url": "https://api.anthropic.com", "default_model": "claude-sonnet-4-5", "env_var": "ANTHROPIC_API_KEY",
         "note": "Requires a Claude API key; a Claude subscription does not include API credits."},
        {"type": "openrouter", "label": "OpenRouter", "requires_key": True, "local": False,
         "base_url": "https://openrouter.ai/api/v1", "default_model": "openai/gpt-4.1-mini", "env_var": "OPENROUTER_API_KEY",
         "note": "One key for many models; pricing is model-specific and must be configured for cost estimates."},
        {"type": "gemini", "label": "Google Gemini API", "requires_key": True, "local": False,
         "base_url": "https://generativelanguage.googleapis.com/v1beta", "default_model": "gemini-2.0-flash", "env_var": "GEMINI_API_KEY",
         "note": "Google AI Studio API key; free tier availability depends on the model and account."},
        {"type": "ollama", "label": "Ollama (local)", "requires_key": False, "local": True,
         "base_url": "http://localhost:11434/v1", "default_model": "gemma:2b", "env_var": "",
         "note": "Runs on your machine. No API charge; quality/speed depend on the local model."},
        {"type": "vllm", "label": "vLLM / local inference", "requires_key": False, "local": True,
         "base_url": "http://localhost:8000/v1", "default_model": "", "env_var": "VLLM_API_KEY",
         "note": "OpenAI-compatible self-hosted server."},
        {"type": "custom_openai", "label": "Custom OpenAI-compatible", "requires_key": True, "local": False,
         "base_url": "https://your-provider.example/v1", "default_model": "", "env_var": "CUSTOM_OPENAI_API_KEY",
         "note": "Any endpoint implementing /chat/completions and optionally /models."},
        {"type": "azure_openai", "label": "Azure OpenAI", "requires_key": True, "local": False,
         "base_url": "https://YOUR-RESOURCE.openai.azure.com", "default_model": "deployment-name", "env_var": "AZURE_OPENAI_API_KEY",
         "note": "Uses deployment name as the model and an api-version parameter."},
    ]
