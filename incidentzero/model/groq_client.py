from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from groq import Groq

from incidentzero.domain.models import ModelReply, ToolCall
from .errors import PermanentModelError, TransientModelError


class GroqModelClient:
    def __init__(self, api_key: str | None = None, model: str = "openai/gpt-oss-20b") -> None:
        self.model = model
        self.client = Groq(api_key=api_key or os.getenv("GROQ_API_KEY"))

    def _translate_error(self, exc: Exception) -> Exception:
        status = getattr(exc, "status_code", None)
        err_msg = str(exc)
        if "tool_use_failed" in err_msg or "Failed to parse tool call arguments" in err_msg:
            return TransientModelError(err_msg)
        if status in {408, 409, 429, 500, 502, 503, 504}:
            return TransientModelError(err_msg)
        return PermanentModelError(err_msg)

    def _try_recover_failed_generation(
        self, exc: Exception, tools: list[dict[str, Any]]
    ) -> ModelReply | None:
        try:
            failed_gen = None
            body = getattr(exc, "body", None)
            if isinstance(body, dict):
                error_obj = body.get("error")
                if isinstance(error_obj, dict):
                    failed_gen = error_obj.get("failed_generation")

            if not failed_gen and hasattr(exc, "response") and hasattr(exc.response, "json"):
                try:
                    resp_json = exc.response.json()
                    if isinstance(resp_json, dict):
                        failed_gen = resp_json.get("error", {}).get("failed_generation")
                except Exception:
                    pass

            if not failed_gen:
                err_str = str(exc)
                if "failed_generation" in err_str:
                    m = re.search(r"['\"]failed_generation['\"]\s*:\s*['\"](\{.*?\})['\"]", err_str)
                    if m:
                        raw = m.group(1).encode().decode("unicode_escape", errors="ignore")
                        failed_gen = raw

            data: dict[str, Any] = {}
            if isinstance(failed_gen, str):
                try:
                    data = json.loads(failed_gen)
                except Exception:
                    name_match = re.search(r'["\']name["\']\s*:\s*["\']([^"\']+)["\']', failed_gen)
                    data = {"name": name_match.group(1) if name_match else ""}
            elif isinstance(failed_gen, dict):
                data = failed_gen
            else:
                return None

            raw_name = str(data.get("name", ""))
            clean_name = re.sub(r"<\|.*", "", raw_name).strip()

            valid_tool_names = {
                t["function"]["name"]
                for t in tools
                if isinstance(t, dict) and "function" in t and "name" in t["function"]
            }
            if clean_name not in valid_tool_names:
                for vname in valid_tool_names:
                    if clean_name.startswith(vname) or raw_name.startswith(vname):
                        clean_name = vname
                        break

            if clean_name not in valid_tool_names:
                return None

            raw_args = data.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            call_id = f"call_{uuid.uuid4().hex[:8]}"
            return ModelReply(
                content=None,
                tool_calls=[ToolCall(id=call_id, name=clean_name, arguments=args)],
                usage={},
                finish_reason="tool_calls",
            )
        except Exception:
            return None

    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                temperature=0.1,
                reasoning_effort="low",
            )
        except Exception as exc:  # provider-specific classes intentionally kept out of student code
            recovered = self._try_recover_failed_generation(exc, tools)
            if recovered is not None:
                return recovered
            raise self._translate_error(exc) from exc
        msg = response.choices[0].message
        calls: list[ToolCall] = []
        for call in (msg.tool_calls or []):
            try:
                args = json.loads(call.function.arguments)
            except Exception:
                args = {"__malformed_arguments__": call.function.arguments}
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=args))
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            }
        return ModelReply(
            content=msg.content,
            tool_calls=calls,
            usage=usage,
            finish_reason=response.choices[0].finish_reason,
        )

    def structured(self, messages: list[dict[str, Any]], schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
                temperature=0.1,
                reasoning_effort="low",
            )
        except Exception as exc:
            raise self._translate_error(exc) from exc
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise TransientModelError(f"Model returned invalid structured JSON: {content[:160]}") from exc
