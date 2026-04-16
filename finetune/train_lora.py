"""
train_lora.py  —  Fine-tune meta-llama-3-8b-instruct on GTX 3080 (10GB)
=======================================================================
Uses Unsloth for 4-bit quantized LoRA training.
Fits comfortably in 10GB VRAM.

Steps:
  1. python prepare_training_data.py      # builds training_data.jsonl
  2. python train_lora.py                 # trains ~15-25 min on 3080
  3. Load output/lora_model in LM Studio  # or convert to GGUF below

GGUF export (run after training):
  python train_lora.py --export-gguf
"""

import argparse
import json
import os
from pathlib import Path

# ── parse args ───────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--export-gguf", action="store_true",
                    help="Export the saved LoRA model to GGUF (for LM Studio)")
parser.add_argument("--data",    default="training_data.jsonl")
parser.add_argument("--output",  default="output/lora_model")
parser.add_argument("--epochs",  type=int, default=3)
parser.add_argument("--lr",      type=float, default=2e-4)
parser.add_argument("--max-len", type=int, default=2048)
args = parser.parse_args()

SCRIPT_DIR  = Path(__file__).parent
DATA_FILE   = SCRIPT_DIR / args.data
OUTPUT_DIR  = SCRIPT_DIR / args.output
GGUF_DIR    = SCRIPT_DIR / "output" / "gguf"

# ── lazy imports (only load after arg check) ─────────────────────────────────
def run_training():
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template
    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments
    import torch

    print("=" * 60)
    print("  Fine-tuning meta-llama-3-8b-instruct with LoRA + Unsloth")
    print("=" * 60)

    # ── 1. Load base model (4-bit) ────────────────────────────────────────────
    print("\n[1/4] Loading base model (4-bit quantized)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name    = "unsloth/Meta-Llama-3-8B-Instruct-bnb-4bit",
        max_seq_length= args.max_len,
        dtype         = None,   # auto-detect (bfloat16 on Ampere+)
        load_in_4bit  = True,
    )

    tokenizer = get_chat_template(tokenizer, chat_template="llama-3")

    # ── 2. Apply LoRA ─────────────────────────────────────────────────────────
    print("[2/4] Applying LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r                   = 16,        # LoRA rank — 16 is good for 10GB
        target_modules      = ["q_proj", "k_proj", "v_proj", "o_proj",
                               "gate_proj", "up_proj", "down_proj"],
        lora_alpha          = 16,
        lora_dropout        = 0,
        bias                = "none",
        use_gradient_checkpointing = "unsloth",  # saves ~30% VRAM
        random_state        = 42,
    )

    # ── 3. Load dataset ───────────────────────────────────────────────────────
    print(f"[3/4] Loading training data from {DATA_FILE}...")
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

    print(f"  Loaded {len(rows)} training examples")

    def format_example(row):
        """Apply Llama-3 chat template to a messages list."""
        text = tokenizer.apply_chat_template(
            row["messages"],
            tokenize          = False,
            add_generation_prompt = False,
        )
        return {"text": text}

    dataset = Dataset.from_list(rows).map(format_example, batched=False)
    print(f"  Dataset size: {len(dataset)} rows")

    # ── 4. Train ──────────────────────────────────────────────────────────────
    print(f"[4/4] Starting training ({args.epochs} epochs, lr={args.lr})...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    trainer = SFTTrainer(
        model     = model,
        tokenizer = tokenizer,
        train_dataset = dataset,
        dataset_text_field = "text",
        max_seq_length     = args.max_len,
        dataset_num_proc   = 2,
        args = TrainingArguments(
            per_device_train_batch_size  = 1,
            gradient_accumulation_steps  = 8,   # effective batch = 8
            warmup_steps                 = 5,
            num_train_epochs             = args.epochs,
            learning_rate                = args.lr,
            fp16                         = not torch.cuda.is_bf16_supported(),
            bf16                         = torch.cuda.is_bf16_supported(),
            logging_steps                = 5,
            optim                        = "adamw_8bit",
            weight_decay                 = 0.01,
            lr_scheduler_type            = "cosine",
            seed                         = 42,
            output_dir                   = str(OUTPUT_DIR / "checkpoints"),
            report_to                    = "none",
        ),
    )

    gpu_stats = torch.cuda.get_device_properties(0)
    print(f"\n  GPU: {gpu_stats.name}  |  VRAM: {gpu_stats.total_memory / 1e9:.1f} GB")
    reserved = torch.cuda.memory_reserved() / 1e9
    print(f"  Reserved before training: {reserved:.1f} GB\n")

    trainer_stats = trainer.train()

    # ── Save LoRA adapters ────────────────────────────────────────────────────
    model.save_pretrained(str(OUTPUT_DIR))
    tokenizer.save_pretrained(str(OUTPUT_DIR))

    mins  = trainer_stats.metrics["train_runtime"] / 60
    print(f"\nTraining complete in {mins:.1f} minutes")
    print(f"LoRA adapters saved to: {OUTPUT_DIR}")
    print("\nNext step — export to GGUF for LM Studio:")
    print("  python train_lora.py --export-gguf")


def run_gguf_export():
    from unsloth import FastLanguageModel

    print("Exporting LoRA model to GGUF (q4_k_m)...")
    GGUF_DIR.mkdir(parents=True, exist_ok=True)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name    = str(OUTPUT_DIR),
        max_seq_length= args.max_len,
        dtype         = None,
        load_in_4bit  = True,
    )

    # q4_k_m is the best balance of size/quality for LM Studio
    model.save_pretrained_gguf(
        str(GGUF_DIR),
        tokenizer,
        quantization_method = "q4_k_m",
    )
    gguf_files = list(GGUF_DIR.glob("*.gguf"))
    print(f"\nGGUF saved to: {GGUF_DIR}")
    for f in gguf_files:
        print(f"  {f.name}  ({f.stat().st_size / 1e9:.2f} GB)")
    print("\nLoad in LM Studio:")
    print("  File → Load model → browse to the .gguf file above")


# ── entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if args.export_gguf:
        run_gguf_export()
    else:
        run_training()
