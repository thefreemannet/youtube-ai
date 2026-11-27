"""Draw one vertical cartoon on the GPU machine.

This replaces the paid picture call. The voice service and the video service
stay as they are. The model is FLUX.2 Klein 4B, which can be used commercially.
"""

import base64
import gc
import io
import json
import threading
import time
import urllib.request

import torch
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

MODEL_ID = "black-forest-labs/FLUX.2-klein-4B"
_lock = threading.Lock()
_pipe = None

app = FastAPI(title="J3G local cartoons")


class PictureRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    width: int = 720
    height: int = 1280
    reference_png_base64: str | None = None


def _snap(value):
    return max(256, min(1280, int(value) // 16 * 16))


def _free_script_model():
    """Ask Ollama to drop the script model so this GPU can draw a picture."""
    body = json.dumps({"model": "qwen3.5:9b", "keep_alive": 0, "prompt": " "}).encode("utf-8")
    request = urllib.request.Request(
        "http://192.168.120.107:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
    except Exception:
        return
    time.sleep(1)


def _release(pipe):
    """Drop the picture model so the voice and the script model can use the GPU."""
    global _pipe
    _pipe = None
    if pipe is not None:
        for name in ("transformer", "vae", "text_encoder"):
            module = getattr(pipe, name, None)
            if module is not None and hasattr(module, "to"):
                try:
                    module.to("cpu")
                except Exception:
                    pass
                try:
                    setattr(pipe, name, None)
                except Exception:
                    pass
        del pipe
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _load():
    global _pipe
    if _pipe is not None:
        return _pipe
    from diffusers import Flux2KleinPipeline

    pipe = Flux2KleinPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    # The voice model already occupies part of the GPU. Keep the text encoder
    # in system memory and put only the drawing network on the GPU.
    pipe.text_encoder.to("cpu")
    pipe.transformer.to("cuda")
    pipe.vae.to("cuda")
    if hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
    _pipe = pipe
    return pipe


@app.get("/health")
def health():
    free = 0
    if torch.cuda.is_available():
        free = torch.cuda.mem_get_info()[0]
    return {"ok": True, "loaded": _pipe is not None, "model": MODEL_ID, "gpu_free_bytes": free}


def _reference(encoded, width, height):
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
        picture = Image.open(io.BytesIO(raw)).convert("RGB")
    except (ValueError, OSError) as exc:
        raise HTTPException(400, "The reference picture could not be read") from exc
    return picture.resize((width, height), Image.Resampling.LANCZOS)


@app.post("/v1/images")
def images(body: PictureRequest):
    width = _snap(body.width)
    height = _snap(body.height)
    reference = _reference(body.reference_png_base64, width, height)
    prompt = " ".join(body.prompt.split())
    with _lock:
        pipe = None
        _free_script_model()
        try:
            pipe = _load()

            def draw(draw_width, draw_height, draw_reference):
                return pipe(
                    prompt=prompt,
                    image=draw_reference,
                    width=draw_width,
                    height=draw_height,
                    guidance_scale=1.0,
                    num_inference_steps=4,
                )

            try:
                result = draw(width, height, reference)
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                gc.collect()
                small_w, small_h = _snap(576), _snap(1024)
                small_reference = reference.resize((small_w, small_h), Image.Resampling.LANCZOS) if reference is not None else None
                result = draw(small_w, small_h, small_reference)
            image = result.images[0]
        except torch.cuda.OutOfMemoryError as exc:
            raise HTTPException(503, "The local picture model ran out of GPU memory") from exc
        finally:
            _release(pipe)
            pipe = None
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"data": [{"b64_json": encoded}]}
