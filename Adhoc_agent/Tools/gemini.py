"""Two bounded structured calls per request; no automatic provider retries."""

import json
from typing import Protocol, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from Adhoc_agent.models import WorkflowError

T = TypeVar("T", bound=BaseModel)


class ModelClient(Protocol):
    label: str

    def generate(self, instruction: str, payload: dict, response_type: type[T]) -> T: ...


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise WorkflowError("Set GEMINI_API_KEY in the local .env file before running Gemini.")
        self.label = model
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=30000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate(self, instruction: str, payload: dict, response_type: type[T]) -> T:
        try:
            response = self.client.models.generate_content(
                model=self.label,
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=instruction,
                    response_mime_type="application/json",
                    response_json_schema=response_type.model_json_schema(),
                    temperature=0,
                    max_output_tokens=8192,
                ),
            )
        except Exception as exc:
            # Provider errors may contain URLs or credential-bearing request details.
            if "api key not valid" in str(getattr(exc, "message", "")).lower():
                raise WorkflowError(
                    "Google rejected GEMINI_API_KEY as invalid. Update the local .env file."
                ) from exc
            raise WorkflowError(
                "Gemini request failed. Check the key, model, quota and network; "
                "no automatic retry was made."
            ) from exc
        try:
            if not response.text:
                raise WorkflowError("Gemini returned no structured response.")
            return response_type.model_validate_json(response.text)
        except (ValidationError, ValueError) as exc:
            raise WorkflowError("Gemini returned invalid structured output.") from exc

    def close(self):
        self.client.close()
