"""
JARVIS Home Server — FastAPI + WebSocket for offloaded ML workloads.

Provides:
- /health — server health check
- /vision (WebSocket) — streaming JPEG → detections
- /vision/identify (POST) — face identification
- /vision/detect (POST) — YOLO object detection
- /llm/generate (POST) — Ollama LLM queries
"""

import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("jarvis-server")

app = FastAPI(title="JARVIS Server", version="1.0.0")

# Lazy-load services to avoid import errors if deps are missing
_face_service = None
_yolo_service = None
_ollama_service = None
_voice_service = None
_person_registry = None


def get_face_service():
    global _face_service
    if _face_service is None:
        from services.face_service import FaceService
        _face_service = FaceService()
    return _face_service


def get_yolo_service():
    global _yolo_service
    if _yolo_service is None:
        from services.yolo_service import YOLOService
        _yolo_service = YOLOService()
    return _yolo_service


def get_ollama_service():
    global _ollama_service
    if _ollama_service is None:
        from services.ollama_service import OllamaService
        _ollama_service = OllamaService()
    return _ollama_service


def get_voice_service():
    global _voice_service
    if _voice_service is None:
        from services.voice_service import VoiceService
        _voice_service = VoiceService()
    return _voice_service


def get_person_registry():
    global _person_registry
    if _person_registry is None:
        from services.person_registry import PersonRegistry
        _person_registry = PersonRegistry()
    return _person_registry


# ── Health ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "services": {
            "face": _face_service is not None,
            "yolo": _yolo_service is not None,
            "ollama": _ollama_service is not None,
            "voice": _voice_service is not None,
            "person_registry": _person_registry is not None,
        },
    }


# ── Vision WebSocket (streaming frames) ──────────────────────────────

@app.websocket("/vision")
async def vision_ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("Vision WebSocket connected")

    face_svc = get_face_service()
    yolo_svc = get_yolo_service()

    try:
        while True:
            jpeg_bytes = await websocket.receive_bytes()

            # Run face + YOLO in parallel
            face_task = asyncio.create_task(
                asyncio.to_thread(face_svc.identify, jpeg_bytes)
            )
            yolo_task = asyncio.create_task(
                asyncio.to_thread(yolo_svc.detect, jpeg_bytes)
            )

            faces, objects = await asyncio.gather(face_task, yolo_task)

            await websocket.send_json({
                "faces": faces,
                "objects": objects,
            })
    except WebSocketDisconnect:
        logger.info("Vision WebSocket disconnected")
    except Exception:
        logger.exception("Vision WebSocket error")


# ── Face Identification (single frame) ───────────────────────────────

@app.post("/vision/identify")
async def identify_face(image: UploadFile = File(...)):
    jpeg_bytes = await image.read()
    face_svc = get_face_service()
    result = await asyncio.to_thread(face_svc.identify, jpeg_bytes)
    if result:
        return result[0] if isinstance(result, list) else result
    return {"name": None, "confidence": 0}


# ── YOLO Object Detection (single frame) ─────────────────────────────

@app.post("/vision/detect")
async def detect_objects(image: UploadFile = File(...)):
    jpeg_bytes = await image.read()
    yolo_svc = get_yolo_service()
    detections = await asyncio.to_thread(yolo_svc.detect, jpeg_bytes)
    return {"detections": detections}


# ── Ollama LLM ───────────────────────────────────────────────────────

# ── Face Registration ────────────────────────────────────────────────

@app.post("/vision/register_face")
async def register_face(name: str = Form(...), image: UploadFile = File(...)):
    jpeg_bytes = await image.read()
    face_svc = get_face_service()
    registry = get_person_registry()
    ok = await asyncio.to_thread(face_svc.register_face, name, jpeg_bytes)
    if ok:
        registry.register(name, modality="face")
        return {"status": "ok", "name": name}
    return JSONResponse(status_code=400, content={"status": "error", "message": "No face found in image"})


# ── Voice Enrollment ─────────────────────────────────────────────────

@app.post("/voice/enroll")
async def enroll_voice(name: str = Form(...), audio: UploadFile = File(...)):
    """Enroll a speaker voice from PCM16 WAV or raw 16kHz PCM audio."""
    audio_bytes = await audio.read()
    voice_svc = get_voice_service()
    registry = get_person_registry()

    import numpy as np
    # Try WAV first, fall back to raw PCM
    try:
        import wave
        import io
        with wave.open(io.BytesIO(audio_bytes)) as wf:
            sr = wf.getframerate()
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    except Exception:
        sr = 16000
        pcm = np.frombuffer(audio_bytes, dtype=np.int16)

    ok = await asyncio.to_thread(voice_svc.enroll, name, pcm, sr)
    if ok:
        registry.register(name, modality="voice")
        return {"status": "ok", "name": name}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Audio too short (need 1+ seconds)"})


@app.post("/voice/identify")
async def identify_voice(audio: UploadFile = File(...)):
    """Identify a speaker from audio."""
    audio_bytes = await audio.read()
    voice_svc = get_voice_service()

    import numpy as np
    try:
        import wave
        import io
        with wave.open(io.BytesIO(audio_bytes)) as wf:
            sr = wf.getframerate()
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    except Exception:
        sr = 16000
        pcm = np.frombuffer(audio_bytes, dtype=np.int16)

    result = await asyncio.to_thread(voice_svc.identify, pcm, sr)
    return result


# ── Person Registry ──────────────────────────────────────────────────

@app.get("/person/{name}")
async def get_person(name: str):
    registry = get_person_registry()
    person = registry.get_person(name)
    if person:
        return person
    return JSONResponse(status_code=404, content={"status": "not_found"})


@app.get("/persons")
async def list_persons():
    registry = get_person_registry()
    return {"persons": registry.list_persons()}


@app.post("/person/{name}/preference")
async def set_preference(name: str, body: dict):
    registry = get_person_registry()
    for k, v in body.items():
        registry.set_preference(name, k, v)
    return {"status": "ok"}


@app.post("/person/{name}/encounter")
async def record_encounter(name: str):
    registry = get_person_registry()
    person = registry.record_encounter(name)
    if person:
        return person
    return JSONResponse(status_code=404, content={"status": "not_found"})


@app.post("/person/{name}/notes")
async def set_notes(name: str, body: dict):
    registry = get_person_registry()
    notes = body.get("notes", "")
    registry.set_notes(name, notes)
    return {"status": "ok"}


# ── Ollama LLM ───────────────────────────────────────────────────────

@app.post("/llm/generate")
async def generate(body: dict):
    prompt = body.get("prompt", "")
    system = body.get("system", "")
    ollama_svc = get_ollama_service()
    response = await asyncio.to_thread(ollama_svc.generate, prompt, system)
    return {"response": response}


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
