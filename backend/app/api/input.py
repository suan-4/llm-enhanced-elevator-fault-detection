"""Local-only explicit offline input, including login fields."""
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from app.services import offline_input as engine

router = APIRouter(prefix='/api/input', tags=['离线输入'])


def require_local(request):
    host = request.client.host if request.client else ''
    origin = request.headers.get('origin', '')
    if host not in ('127.0.0.1', '::1', '::ffff:127.0.0.1'):
        raise HTTPException(403, '仅允许在本机操作输入面板')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, '输入面板不接受其他网站请求')
    if request.headers.get('x-elevator-input') != '1':
        raise HTTPException(403, '请使用本机输入面板')


class PinyinRequest(BaseModel):
    actions: list[dict] = Field(default_factory=list, max_length=160)


class RecordingRequest(BaseModel):
    id: str = Field(min_length=32, max_length=32, pattern='^[a-f0-9]+$')


@router.get('/status')
def input_status(request: Request):
    require_local(request)
    return engine.status()


@router.post('/pinyin')
def pinyin(request: Request, body: PinyinRequest):
    require_local(request)
    try:
        return engine.pinyin(body.actions)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/voice/start')
def voice_start(request: Request):
    require_local(request)
    if not engine.status()['voice']:
        raise HTTPException(503, '离线语音模型尚未安装')
    try:
        return engine.voice.start()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/voice/stop')
def voice_stop(request: Request, body: RecordingRequest):
    require_local(request)
    try:
        return engine.voice.stop(body.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/voice/cancel')
def voice_cancel(request: Request, body: RecordingRequest):
    require_local(request)
    try:
        engine.voice.cancel(body.id)
        return {'success': True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
