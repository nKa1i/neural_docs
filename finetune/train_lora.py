"""
train_lora.py  —  Fine-tune Llama-3-8B on GTX 3080 (no Unsloth/Triton)
=======================================================================
Uses standard transformers + PEFT + bitsandbytes.
Works natively on Windows, no triton required.

Steps:
  1. python prepare_training_data.py      # builds training_data.jsonl
  2. python train_lora.py                 # trains ~20-35 min on 3080
  3. python train_lora.py --export-gguf   # convert for LM Studio

Model: NousResearch/Meta-Llama-3-8B-Instruct
  (public mirror of Meta-Llama-3-8B-Instruct, no HuggingFace gate needed)
"""

import argparse
import json
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--export-gguf", action="store_true")
parser.add_argument("--data",    default="training_data.jsonl")
parser.add_argument("--output",  default="output/lora_model")
parser.add_argument("--epochs",  type=int,   default=3)
parser.add_argument("--lr",      type=float, default=2e-4)
parser.add_argument("--max-len", type=int,   default=2048)
args = parser.parse_args()

SCRIPT_DIR = Path(__file__).parent
DATA_FILE  = SCRIPT_DIR / args.data
OUTPUT_DIR = SCRIPT_DIR / args.output
GGUF_DIR   = SCRIPT_DIR / "output" / "gguf"

MODEL_NAME = "NousResearch/Meta-Llama-3-8B-Instruct"


def run_training():
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )
    from peft import (
        LoraConfig,
        get_peft_model,
        prepare_model_for_kbit_training,
        TaskType,
    )
    from trl import SFTTrainer, SFTConfig
    from datasets import Dataset

    print("=" * 60)
    print("  Llama-3-8B LoRA Fine-Tuning  (transformers + PEFT)")
    print("=" * 60)

    # ── GPU check ─────────────────────────────────────────────────────────────
    if not torch.cuda.is_available():
        print("ERROR: CUDA not available. Check your PyTorch install.")
        return
    gpu = torch.cuda.get_device_properties(0)
    print(f"\nGPU: {gpu.name}  |  VRAM: {gpu.total_memory / 1e9:.1f} GB")

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    # ── 1. Load model in 4-bit ────────────────────────────────────────────────
    print("\n[1/4] Loading base model (4-bit NF4)...")
    print(f"      {MODEL_NAME}")
    print("      First run downloads ~5GB — please wait...\n")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=dtype,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── 2. Apply LoRA ─────────────────────────────────────────────────────────
    print("[2/4] Applying LoRA (r=16)...")
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=16,
        lora_alpha=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_dropout=0.0,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── 3. Load dataset ───────────────────────────────────────────────────────
    print(f"\n[3/4] Loading training data from {DATA_FILE.name}...")
    if not DATA_FILE.exists():
        print(f"\nERROR: {DATA_FILE} not found.")
        print("Run:  python prepare_training_data.py  first.")
        return

    rows = []
    with open(DATA_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    def format_chat(row):
        """Convert messages list to Llama-3 chat template string."""
        parts = []
        for msg in row["messages"]:
            role    = msg["role"]
            content = msg["content"]
            if role == "system":
                parts.append(f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{content}<|eot_id|>")
            elif role == "user":
                parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{content}<|eot_id|>")
            elif role == "assistant":
                parts.append(f"<|start_header_id|>assistant<|end_header_id|>\n\n{content}<|eot_id|>")
        return {"text": "".join(parts)}

    dataset = Dataset.from_list(rows).map(format_chat, batched=False)
    print(f"  {len(dataset)} training examples ready")

    # ── 4. Train ──────────────────────────────────────────────────────────────
    print(f"\n[4/4] Training ({args.epochs} epochs, lr={args.lr})...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    training_args = SFTConfig(
        output_dir                  = str(OUTPUT_DIR / "checkpoints"),
        num_train_epochs            = args.epochs,
        per_device_train_batch_size = 1,
        gradient_accumulation_steps = 8,
        warmup_steps                = 5,
        learning_rate               = args.lr,
        fp16                        = (dtype == torch.float16),
        bf16                        = (dtype == torch.bfloat16),
        logging_steps               = 5,
        optim                       = "paged_adamw_8bit",
        weight_decay                = 0.01,
        lr_scheduler_type           = "cosine",
        seed                        = 42,
        report_to                   = "none",
        max_seq_length              = args.max_len,
        dataset_text_field          = "text",
        packing                     = False,
    )

    trainer = SFTTrainer(
        model            = model,
        processing_class = tokenizer,
        train_dataset    = dataset,
        args             = training_args,
    )

    trainer_stats = trainer.train()

    model.save_pretrained(str(OUTPUT_DIR))
    tokenizer.save_pretrained(str(OUTPUT_DIR))

    mins = trainer_stats.metrics["train_runtime"] / 60
    loss = trainer_stats.metrics.get("train_loss", "?")
    print(f"\nDone in {mins:.1f} min  |  final loss: {loss}")
    print(f"LoRA adapters saved → {OUTPUT_DIR}")
    print("\nNext: python train_lora.py --export-gguf")


def run_gguf_export():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    print("Merging LoRA adapters into base model (runs on CPU)...")
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    merged_dir = SCRIPT_DIR / "output" / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)

    base = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)

    print("Merging LoRA weights...")
    model = PeftModel.from_pretrained(base, str(OUTPUT_DIR))
    model = model.merge_and_unload()

    print(f"Saving merged model → {merged_dir}")
    model.save_pretrained(str(merged_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(merged_dir))

    print("\nMerged model saved.")
    print("Load directly in LM Studio: File → Load Model → browse to:")
    print(f"  {merged_dir}")
    print("\nOr convert to GGUF with llama.cpp:")
    print(f"  python llama.cpp/convert_hf_to_gguf.py {merged_dir} --outtype q4_k_m --outfile {GGUF_DIR}/model-q4_k_m.gguf")


if __name__ == "__main__":
    if args.export_gguf:
        run_gguf_export()
    else:
        run_training()
