import os
import shutil
import time
import asyncio
from fastapi import FastAPI
from app.api.routes import router

app = FastAPI()
app.include_router(router)

SAMPLES_DIR = os.path.join(os.getcwd(), "tests/dummy_data")


@app.on_event("startup")
async def start_cleanup():
    asyncio.create_task(_cleanup_old_sessions())


async def _cleanup_old_sessions():
    """Delete session folders older than 24 hours. Runs hourly."""
    while True:
        await asyncio.sleep(3600)
        cutoff = time.time() - 86400
        if os.path.isdir(SAMPLES_DIR):
            for entry in os.scandir(SAMPLES_DIR):
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
