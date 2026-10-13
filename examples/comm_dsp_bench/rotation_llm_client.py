"""Narrow OpenAI-compatible client for the bounded rotation LLM experiment.

There is no automatic retry.  Each call either records one provider response
or one failure; the experiment runner owns retry and budget decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlsplit


INPUT_TOKEN_LIMIT = 8000
OUTPUT_TOKEN_LIMIT = 4000
MESSAGE_WRAPPER_RESERVE_BYTES = 1024
PER_MESSAGE_RESERVE_BYTES = 64
_CLIENT_FACTORY = None


class InvalidResponseError(ValueError):
    pass


def _redact(value: object, secrets: tuple[str, ...]) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED]", text)
    return text


def _read_key(api_key_env: str, key_file: str | Path | None) -> tuple[str, str]:
    if key_file is not None:
        try:
            key = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"cannot read explicit key file: {type(exc).__name__}") from exc
        source = "key_file"
    else:
        if not api_key_env or not isinstance(api_key_env, str):
            raise ValueError("api_key_env must name an explicit environment variable")
        key = os.environ.get(api_key_env, "").strip()
        source = f"env:{api_key_env}"
    if not key or any(character.isspace() for character in key):
        raise ValueError(f"missing or invalid API key from {source}")
    return key, source


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"request must be JSON serializable: {exc}") from exc


def conservative_input_token_bound(
    messages: list[dict], extra_body: dict | None = None
) -> dict:
    """Bound input tokens by UTF-8 bytes plus explicit chat-wrapper reserve.

    A tokenizer token cannot consume fewer than one encoded byte.  The reserve
    covers role separators and provider chat framing not present in content.
    This bound is intentionally conservative and may reject valid prompts.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a nonempty list")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"message {index} must be an object")
        if message.get("role") not in {"system", "user", "assistant"}:
            raise ValueError(f"message {index} has unsupported role")
        if "content" not in message:
            raise ValueError(f"message {index} has no content")
    message_bytes = len(_json_bytes(messages))
    extra_bytes = len(_json_bytes(extra_body)) if extra_body is not None else 0
    reserve = MESSAGE_WRAPPER_RESERVE_BYTES + PER_MESSAGE_RESERVE_BYTES * len(messages)
    upper = message_bytes + extra_bytes + reserve
    return {
        "method": "utf8_bytes_plus_chat_wrapper_reserve",
        "message_utf8_bytes": message_bytes,
        "extra_body_utf8_bytes": extra_bytes,
        "wrapper_reserve_bytes": reserve,
        "upper_bound_tokens": upper,
        "limit_tokens": INPUT_TOKEN_LIMIT,
        "within_limit": upper <= INPUT_TOKEN_LIMIT,
    }


def _to_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json", exclude_none=False)
        if isinstance(dumped, dict):
            return dumped
    raise InvalidResponseError("provider returned a response that cannot be serialized")


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage(raw_usage: object, max_output_tokens: int) -> dict:
    if not isinstance(raw_usage, dict):
        return {
            "status": "unknown",
            "reported": False,
            "raw": None,
            "input_tokens": None,
            "output_tokens": None,
            "cache_tokens": None,
            "total_tokens": None,
            "actual_billed_cost": None,
            "accounting": {
                "source": "reserved_limits",
                "input_tokens": INPUT_TOKEN_LIMIT,
                "output_tokens": max_output_tokens,
            },
        }
    input_tokens = _integer(raw_usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _integer(raw_usage.get("prompt_tokens"))
    output_tokens = _integer(raw_usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _integer(raw_usage.get("completion_tokens"))
    total_tokens = _integer(raw_usage.get("total_tokens"))
    details = raw_usage.get("prompt_tokens_details") or raw_usage.get("input_tokens_details")
    cache_tokens = None
    if isinstance(details, dict):
        cache_tokens = _integer(details.get("cached_tokens"))
    for key in ("prompt_cache_hit_tokens", "cache_read_input_tokens", "cached_tokens"):
        if cache_tokens is None:
            cache_tokens = _integer(raw_usage.get(key))
    actual = None
    for key in ("actual_billed_cost", "billed_cost", "cost"):
        if key in raw_usage and raw_usage[key] is not None:
            actual = raw_usage[key]
            break
    return {
        "status": "reported",
        "reported": True,
        "raw": raw_usage,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_tokens": cache_tokens,
        "total_tokens": total_tokens,
        "actual_billed_cost": actual,
        "accounting": {
            "source": "reported_usage" if input_tokens is not None and output_tokens is not None else "reserved_limits",
            "input_tokens": input_tokens if input_tokens is not None else INPUT_TOKEN_LIMIT,
            "output_tokens": output_tokens if output_tokens is not None else max_output_tokens,
        },
    }


def calculate_cost(usage: dict, tariff: dict) -> dict:
    """Estimate cost from a frozen tariff and reported usage.

    Required tariff keys are ``currency``, ``input_per_million`` and
    ``output_per_million``.  Cached input uses ``cache_input_per_million`` when
    supplied; otherwise it is charged at the ordinary input rate.
    """
    required = ("currency", "input_per_million", "output_per_million")
    if not isinstance(tariff, dict) or any(key not in tariff for key in required):
        raise ValueError("tariff is missing required fields")
    rates = {}
    for key in ("input_per_million", "output_per_million"):
        value = tariff[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid tariff rate: {key}")
        rates[key] = float(value)
    cache_rate = tariff.get("cache_input_per_million", rates["input_per_million"])
    if isinstance(cache_rate, bool) or not isinstance(cache_rate, (int, float)) or not math.isfinite(cache_rate) or cache_rate < 0:
        raise ValueError("invalid tariff rate: cache_input_per_million")
    input_tokens = _integer(usage.get("input_tokens"))
    output_tokens = _integer(usage.get("output_tokens"))
    cache_tokens = _integer(usage.get("cache_tokens")) or 0
    estimate = None
    if input_tokens is not None and output_tokens is not None and cache_tokens <= input_tokens:
        uncached = input_tokens - cache_tokens
        estimate = (
            uncached * rates["input_per_million"]
            + cache_tokens * float(cache_rate)
            + output_tokens * rates["output_per_million"]
        ) / 1_000_000.0
    frozen = json.dumps(tariff, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "currency": tariff["currency"],
        "estimated_cost": estimate,
        "actual_billed_cost": usage.get("actual_billed_cost"),
        "tariff": tariff,
        "tariff_sha256": hashlib.sha256(frozen.encode()).hexdigest(),
        "basis": "reported_usage" if estimate is not None else "unknown_usage",
    }


def _make_client(api_key: str, api_base: str, timeout: float):
    if _CLIENT_FACTORY is not None:
        return _CLIENT_FACTORY(
            api_key=api_key, base_url=api_base.rstrip("/") + "/", timeout=timeout, max_retries=0
        )
    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        base_url=api_base.rstrip("/") + "/",
        timeout=timeout,
        max_retries=0,
    )


def generate(
    messages,
    *,
    model,
    api_base,
    api_key_env="DEEPSEEK_API_KEY",
    key_file=None,
    max_output_tokens=4000,
    timeout=180,
    temperature=0.4,
    seed=None,
    extra_body=None,
) -> dict:
    """Make exactly one OpenAI-compatible chat-completion request."""
    started = time.monotonic()
    base = {
        "status": "invalid_request",
        "text": None,
        "raw_response": None,
        "usage": _usage(
            None,
            max_output_tokens
            if type(max_output_tokens) is int and 1 <= max_output_tokens <= OUTPUT_TOKEN_LIMIT
            else OUTPUT_TOKEN_LIMIT,
        ),
        "elapsed_seconds": 0.0,
        "error": None,
    }
    key = ""
    client = None
    try:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be nonempty")
        if not isinstance(api_base, str) or not re.fullmatch(r"https?://[^\s]+", api_base):
            raise ValueError("api_base must be an explicit HTTP(S) URL")
        parsed_base = urlsplit(api_base)
        if not parsed_base.hostname or parsed_base.username or parsed_base.password:
            raise ValueError("api_base cannot contain credentials")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= OUTPUT_TOKEN_LIMIT:
            raise ValueError(f"max_output_tokens must be in [1, {OUTPUT_TOKEN_LIMIT}]")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be positive")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            raise ValueError("temperature must be finite")
        if seed is not None and (type(seed) is not int or seed < 0):
            raise ValueError("seed must be a nonnegative integer")
        if extra_body is not None and not isinstance(extra_body, dict):
            raise ValueError("extra_body must be an object")
        forbidden = {"messages", "model", "max_tokens", "max_completion_tokens"}
        if extra_body and forbidden.intersection(extra_body):
            raise ValueError("extra_body cannot override core request fields")
        sensitive = {"api_key", "authorization", "headers"}
        if extra_body and sensitive.intersection(key.lower() for key in extra_body):
            raise ValueError("extra_body cannot contain authentication fields")
        bound = conservative_input_token_bound(messages, extra_body)
        if not bound["within_limit"]:
            raise ValueError(
                f"conservative input bound {bound['upper_bound_tokens']} exceeds {INPUT_TOKEN_LIMIT}"
            )
        key, _ = _read_key(api_key_env, key_file)
        client = _make_client(key, api_base, float(timeout))
        request = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens,
            "temperature": float(temperature),
        }
        if seed is not None:
            request["seed"] = seed
        if extra_body is not None:
            request["extra_body"] = extra_body
        response = client.chat.completions.create(**request)
        raw = _to_dict(response)
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise InvalidResponseError("provider response has no completion choice")
        choice = choices[0]
        message = choice.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if text is not None and not isinstance(text, str):
            raise InvalidResponseError("provider response content is not text")
        finish_reason = choice.get("finish_reason")
        usage = _usage(raw.get("usage"), max_output_tokens)
        if usage.get("actual_billed_cost") is None:
            for key_name in ("actual_billed_cost", "billed_cost", "cost"):
                if key_name in raw and raw[key_name] is not None:
                    usage["actual_billed_cost"] = raw[key_name]
                    break
        if finish_reason in {"length", "max_tokens"}:
            status = "truncated"
        elif finish_reason == "stop" and text is not None:
            status = "ok"
        else:
            status = "incomplete"
        base.update(
            status=status,
            text=text,
            raw_response=raw,
            usage=usage,
            error=None,
            response={
                "id": raw.get("id"),
                "model": raw.get("model"),
                "finish_reason": finish_reason,
            },
            input_bound=bound,
        )
    except (TimeoutError,) as exc:
        base.update(status="timeout", error={"type": type(exc).__name__, "message": _redact(exc, (key,))})
    except InvalidResponseError as exc:
        base.update(status="invalid_response", error={"type": type(exc).__name__, "message": _redact(exc, (key,))})
    except ValueError as exc:
        base.update(status="invalid_request", error={"type": type(exc).__name__, "message": _redact(exc, (key,))})
    except Exception as exc:
        name = type(exc).__name__
        status = "timeout" if "timeout" in name.lower() else "api_error"
        base.update(status=status, error={"type": name, "message": _redact(exc, (key,))})
    finally:
        if client is not None and callable(getattr(client, "close", None)):
            try:
                client.close()
            except Exception:
                pass
        base["elapsed_seconds"] = time.monotonic() - started
    return base
