import os
import json
import uuid
from datetime import datetime
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from app.services.llm_provider import LocalProvider
from app.services.export_service import generate_pdf, generate_docx
from app.utils.parsers import extract_text
from app.utils.project_name import extract_project_name
import io

router = APIRouter()

SAMPLES_DIR = os.path.join(os.getcwd(), "tests/dummy_data")
LOCAL_PC_IP  = os.environ.get("LM_STUDIO_HOST",  "host.docker.internal")
LM_MODEL     = os.environ.get("LM_STUDIO_MODEL", "qwen/qwen2.5-v1-7b")
current_llm  = LocalProvider(base_url=f"http://{LOCAL_PC_IP}:1234/v1", model_name=LM_MODEL)

@router.get("/api/samples")
async def list_samples():
    """Return sorted list of available pre-generated JSON samples."""
    if not os.path.isdir(SAMPLES_DIR):
        return JSONResponse({"files": [], "dir": SAMPLES_DIR})
    files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
    return JSONResponse({"files": files, "count": len(files)})

@router.get("/api/samples/{filename}")
async def get_sample(filename: str):
    """Return the content of one sample JSON."""
    # Security: only allow simple filenames, no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(SAMPLES_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, encoding="utf-8") as f:
        return JSONResponse(json.load(f))



@router.get("/")
async def main_page():
    with open("app/frontend/index.html", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@router.post("/generate_document")
async def generate_document(files: List[UploadFile] = File(...), language: str = Form("ru")):
    files_data = []
    for file in files:
        content = await file.read()
        text = extract_text(file.filename, content)
        files_data.append({"filename": file.filename, "content": text})
    try:
        result = current_llm.generate_document(files_data, language=language)

        # Inject human-readable project name into metadata
        if "metadata" not in result:
            result["metadata"] = {}
        result["metadata"]["project_name"] = extract_project_name(result)

        # Save to archive
        os.makedirs(SAMPLES_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:6]
        archive_name = f"analysis_{timestamp}_{short_id}.json"
        archive_path = os.path.join(SAMPLES_DIR, archive_name)
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result
    except Exception as e:
        error_msg = str(e)
        if "Connection error" in error_msg or "ConnectError" in error_msg:
            detail_msg = f"Не удалось подключиться к локальному серверу LM Studio по адресу {LOCAL_PC_IP}."
        else:
            detail_msg = f"Ошибка обработки: {error_msg}"
        raise HTTPException(status_code=500, detail=detail_msg)


@router.post("/export/pdf")
async def export_pdf(request: Request):
    """Generate a PDF from NeuralDocs JSON data. Accepts the full JSON response body."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    language = data.get("_language", "ru")
    try:
        pdf_bytes = generate_pdf(data, language=language)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=neuraldocs_report.pdf",
        },
    )


@router.post("/export/docx")
async def export_docx(request: Request):
    """Generate a DOCX from NeuralDocs JSON data. Accepts the full JSON response body."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    language = data.get("_language", "ru")
    try:
        docx_bytes = generate_docx(data, language=language)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX generation failed: {e}")

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": "attachment; filename=neuraldocs_report.docx",
        },
    )

