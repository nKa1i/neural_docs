"""
serve.py  —  OpenAI-compatible inference server for the fine-tuned model
=========================================================================
Loads the 4-bit base model + LoRA adapters (same config as training,
fits in 10GB VRAM) and serves an OpenAI-compatible API on port 1234.

Your laptop's main.py connects to this exactly like LM Studio — just
change LM_STUDIO_HOST to this PC's IP address.

Usage:
    python serve.py

Then on your laptop set the env var or edit main.py:
    LM_STUDIO_HOST=<this_pc_ip>   (default port 1234)
"""

import json
import time
import uuid
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from peft import PeftModel
from pydantic import BaseModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TextIteratorStreamer,
)

# ── config ───────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
LORA_DIR    = SCRIPT_DIR / "output" / "lora_model"
MODEL_NAME  = "NousResearch/Meta-Llama-3-8B-Instruct"
PORT        = 1234

# ── load model once at startup ───────────────────────────────────────────────
print("=" * 55)
print("  Loading fine-tuned Llama-3-8B + LoRA adapters...")
print("=" * 55)

dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=dtype,
    bnb_4bit_use_double_quant=True,
)

print(f"Base model : {MODEL_NAME}")
base_model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
)

print(f"LoRA adapters: {LORA_DIR}")
if not LORA_DIR.exists():
    raise FileNotFoundError(
        f"LoRA adapters not found at {LORA_DIR}\n"
        "Run  python train_lora.py  first."
    )

model = PeftModel.from_pretrained(base_model, str(LORA_DIR))
model.eval()

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

print(f"\nModel ready — listening on http://0.0.0.0:{PORT}")
print("Point your laptop's main.py to this PC's IP address.\n")

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Fine-tuned Llama-3 inference server")


class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = MODEL_NAME
    messages: list[Message]
    temperature: float = 0.0
    max_tokens: int = 2048
    stream: bool = False


def build_prompt(messages: list[Message]) -> str:
    parts = []
    for msg in messages:
        if msg.role == "system":
            parts.append(
                f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
                f"{msg.content}<|eot_id|>"
            )
        elif msg.role == "user":
            parts.append(
                f"<|start_header_id|>user<|end_header_id|>\n\n"
                f"{msg.content}<|eot_id|>"
            )
        elif msg.role == "assistant":
            parts.append(
                f"<|start_header_id|>assistant<|end_header_id|>\n\n"
                f"{msg.content}<|eot_id|>"
            )
    # Add generation prompt
    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


@app.get("/v1/models")
async def list_models():
    return JSONResponse({
        "object": "list",
        "data": [{"id": MODEL_NAME, "object": "model"}]
    })


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    prompt = build_prompt(req.messages)

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]

    t0 = time.time()
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens   = req.max_tokens,
            temperature      = max(req.temperature, 1e-6),
            do_sample        = req.temperature > 0.01,
            pad_token_id     = tokenizer.eos_token_id,
            eos_token_id     = tokenizer.eos_token_id,
        )

    generated = output_ids[0][input_len:]
    text = tokenizer.decode(generated, skip_special_tokens=True).strip()
    duration_ms = int((time.time() - t0) * 1000)

    return JSONResponse({
        "id":      f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object":  "chat.completion",
        "model":   MODEL_NAME,
        "choices": [{
            "index":         0,
            "message":       {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens":     input_len,
            "completion_tokens": len(generated),
            "total_tokens":      input_len + len(generated),
        },
    })


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
