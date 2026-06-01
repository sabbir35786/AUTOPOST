"""
Image generation provider classes.

Each provider implements a standard interface:
    generate(prompt, negative_prompt, aspect_ratio, model_name, api_key) -> bytes

Aspect ratio mappings and model paths are handled internally per provider.
"""

from __future__ import annotations

import httpx

from app.config import FAL_API_KEY


# ---------------------------------------------------------------------------
# Aspect ratio helpers
# ---------------------------------------------------------------------------

_FAL_ASPECT_MAP: dict[str, str] = {
    "1:1": "square_hd",
    "16:9": "landscape_16_9",
    "4:5": "portrait_4_5",
}

_STABILITY_ASPECT_MAP: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1344, 768),
    "4:5": (896, 1120),
}

_DALLE3_ASPECT_MAP: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "4:5": "1024x1792",
}

_FAL_MODEL_PATHS: dict[str, str] = {
    "FLUX.1-schnell": "fal-ai/flux/schnell",
    "FLUX.1-dev": "fal-ai/flux/dev",
    "FLUX-pro": "fal-ai/flux-pro",
}


# ---------------------------------------------------------------------------
# Provider 1: Fal.ai
# ---------------------------------------------------------------------------

class FalProvider:
    """Image generation via Fal.ai (FLUX models)."""

    AVAILABLE_MODELS = ["FLUX.1-schnell", "FLUX.1-dev", "FLUX-pro"]

    def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        aspect_ratio: str = "1:1",
        model_name: str = "FLUX.1-schnell",
        api_key: str = "",
    ) -> bytes:
        import fal_client  # type: ignore

        effective_key = api_key or FAL_API_KEY
        if not effective_key:
            raise RuntimeError("Fal.ai API key is not configured.")

        import os
        os.environ["FAL_KEY"] = effective_key

        model_path = _FAL_MODEL_PATHS.get(model_name, "fal-ai/flux/schnell")
        image_size = _FAL_ASPECT_MAP.get(aspect_ratio, "square_hd")

        arguments: dict = {
            "prompt": prompt,
            "image_size": image_size,
            "num_inference_steps": 4 if "schnell" in model_path else 28,
            "num_images": 1,
        }
        if negative_prompt:
            arguments["negative_prompt"] = negative_prompt

        result = fal_client.run(model_path, arguments=arguments)

        # Result contains images list; each image has a url field
        images = result.get("images") or []
        if not images:
            raise RuntimeError("Fal.ai returned no images.")
        image_url = images[0]["url"]

        response = httpx.get(image_url, timeout=60)
        response.raise_for_status()
        return response.content


# ---------------------------------------------------------------------------
# Provider 2: Stability AI
# ---------------------------------------------------------------------------

class StabilityProvider:
    """Image generation via Stability AI SDK."""

    AVAILABLE_MODELS = ["stable-diffusion-xl-1024-v1-0", "sd3-medium"]

    def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        aspect_ratio: str = "1:1",
        model_name: str = "stable-diffusion-xl-1024-v1-0",
        api_key: str = "",
    ) -> bytes:
        from app.config import STABILITY_API_KEY as PLATFORM_KEY

        effective_key = api_key or PLATFORM_KEY
        if not effective_key:
            raise RuntimeError("Stability AI API key is not configured.")

        import stability_sdk.client as stability_client  # type: ignore
        from stability_sdk import interfaces as stability_interfaces  # type: ignore
        import grpc  # type: ignore

        width, height = _STABILITY_ASPECT_MAP.get(aspect_ratio, (1024, 1024))

        stability_api = stability_client.StabilityInference(
            key=effective_key,
            verbose=False,
            engine=model_name,
        )

        answers = stability_api.generate(
            prompt=prompt,
            negative_prompt=negative_prompt or "",
            width=width,
            height=height,
            samples=1,
            steps=30,
        )

        for answer in answers:
            for artifact in answer.artifacts:
                if artifact.finish_reason == stability_interfaces.gooseai.generation.generation_pb2.FILTER:
                    raise RuntimeError("Stability AI content filtered the request.")
                if artifact.type == stability_interfaces.gooseai.generation.generation_pb2.ARTIFACT_IMAGE:
                    return artifact.binary

        raise RuntimeError("Stability AI returned no image artifact.")


# ---------------------------------------------------------------------------
# Provider 3: OpenAI DALL-E
# ---------------------------------------------------------------------------

class OpenAIProvider:
    """Image generation via OpenAI DALL-E 2 / DALL-E 3."""

    AVAILABLE_MODELS = ["dall-e-3", "dall-e-2"]

    def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        aspect_ratio: str = "1:1",
        model_name: str = "dall-e-3",
        api_key: str = "",
    ) -> bytes:
        from app.config import OPENAI_API_KEY as PLATFORM_KEY
        from openai import OpenAI  # type: ignore

        effective_key = api_key or PLATFORM_KEY
        if not effective_key:
            raise RuntimeError("OpenAI API key is not configured.")

        client = OpenAI(api_key=effective_key)

        # DALL-E 2 only supports 1024x1024
        if model_name == "dall-e-2":
            size = "1024x1024"
        else:
            size = _DALLE3_ASPECT_MAP.get(aspect_ratio, "1024x1024")

        response = client.images.generate(
            model=model_name,
            prompt=prompt,
            size=size,  # type: ignore[arg-type]
            n=1,
            response_format="url",
        )

        image_url = response.data[0].url
        if not image_url:
            raise RuntimeError("OpenAI DALL-E returned no image URL.")

        resp = httpx.get(image_url, timeout=60)
        resp.raise_for_status()
        return resp.content


# ---------------------------------------------------------------------------
# Provider 4: Google Gemini Imagen
# ---------------------------------------------------------------------------

class GeminiProvider:
    """Image generation via Google Gemini Imagen."""

    AVAILABLE_MODELS = ["imagen-3.0-generate-002"]

    def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        aspect_ratio: str = "1:1",
        model_name: str = "imagen-3.0-generate-002",
        api_key: str = "",
    ) -> bytes:
        from app.config import GEMINI_API_KEY as PLATFORM_KEY
        import google.generativeai as genai  # type: ignore

        effective_key = api_key or PLATFORM_KEY
        if not effective_key:
            raise RuntimeError("Gemini API key is not configured.")

        genai.configure(api_key=effective_key)

        # Gemini Imagen aspect ratio is passed as string directly
        gemini_aspect = aspect_ratio if aspect_ratio in ("1:1", "16:9", "4:5", "3:4", "9:16") else "1:1"

        imagen = genai.ImageGenerationModel(model_name)
        result = imagen.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio=gemini_aspect,
            negative_prompt=negative_prompt or None,
        )

        if not result.images:
            raise RuntimeError("Gemini Imagen returned no images.")

        # Each image has an _image_bytes attribute
        return result.images[0]._image_bytes  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Provider factory / helper
# ---------------------------------------------------------------------------

_PROVIDER_MAP: dict[str, type] = {
    "fal": FalProvider,
    "fal.ai": FalProvider,
    "stability": StabilityProvider,
    "stability_ai": StabilityProvider,
    "openai": OpenAIProvider,
    "dall-e": OpenAIProvider,
    "gemini": GeminiProvider,
    "google": GeminiProvider,
}


def get_image_provider_for_user(user_id: int, db) -> tuple:
    """
    Returns (provider_instance, model_name, api_key) using platform image keys.
    """
    _ = user_id, db
    return FalProvider(), "FLUX.1-schnell", FAL_API_KEY
