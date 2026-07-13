"""MockMate walking skeleton: one spoken interview turn, end to end.

POST /api/transcribe  (audio file)                -> {transcript: str}
POST /api/turn  {history: [...], voice?: str}     -> {reply, audio_b64, provider}

Deliberately no agents, no RAG, no persistence yet — this exists to prove the
voice loop (mic -> STT -> LLM -> TTS audio back) is fast enough to feel like
a conversation before anything bigger is built on top of it.
"""

import base64

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .providers import get_provider
from .stt import SttUnavailableError, transcribe
from .tts import DEFAULT_VOICE, VOICES, synthesize

load_dotenv()

app = FastAPI(title="MockMate")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str
    content: str


class TurnRequest(BaseModel):
    history: list[Message]
    voice: str = DEFAULT_VOICE


class TurnResponse(BaseModel):
    reply: str
    audio_b64: str
    provider: str


@app.get("/api/health")
async def health():
    return {"status": "ok", "provider": get_provider().name}


@app.get("/api/voices")
async def voices():
    return {"voices": VOICES, "default": DEFAULT_VOICE}


@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile):
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="empty audio upload")
    try:
        text = await transcribe(
            audio, file.filename or "answer.webm", file.content_type or "audio/webm"
        )
    except SttUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"transcript": text}


@app.post("/api/turn", response_model=TurnResponse)
async def turn(req: TurnRequest) -> TurnResponse:
    provider = get_provider()
    reply = await provider.chat([m.model_dump() for m in req.history])
    audio = await synthesize(reply, req.voice)
    return TurnResponse(
        reply=reply,
        audio_b64=base64.b64encode(audio).decode(),
        provider=provider.name,
    )
