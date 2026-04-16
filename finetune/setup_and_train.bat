@echo off
echo =============================================
echo  NeonPhantom LoRA Fine-Tune Setup (GTX 3080)
echo =============================================
echo.

:: Step 1 — create venv
echo [1/5] Creating virtual environment...
python -m venv venv_train
call venv_train\Scripts\activate.bat

:: Step 2 — install PyTorch with CUDA 12.1 (matches most RTX 30xx drivers)
echo [2/5] Installing PyTorch (CUDA 12.1)...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet

:: Step 3 — install training deps
echo [3/5] Installing training dependencies...
pip install -r requirements_train.txt --quiet

:: Step 4 — prepare training data
echo [4/5] Preparing training data from finetune_v2 samples...
python prepare_training_data.py

:: Step 5 — run training
echo [5/5] Starting LoRA fine-tuning on GTX 3080...
echo       This takes ~15-25 minutes. Watch the loss drop in the logs.
python train_lora.py

echo.
echo =============================================
echo  Training done! Now exporting to GGUF...
echo =============================================
python train_lora.py --export-gguf

echo.
echo Done. Load output/gguf/*.gguf in LM Studio.
pause
