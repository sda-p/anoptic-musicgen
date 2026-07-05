"""The FastAPI service: one WebSocket carrying bidirectional control + per-bar
telemetry + a ~30 fps meter, plus REST for the schema, sample upload, session
presets, and offline WAV/MIDI export. A single session (one engine + player) is
plenty for a local dev tool; multiple browser tabs just share it and stay in
sync via broadcast snapshots.

Threading: the player runs the engine on its own daemon thread and calls
on_bar there; we marshal each telemetry dict onto the asyncio loop with
call_soon_threadsafe. The meter is read (get_value on a follower) directly from
the loop — a benign cross-thread scalar read.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import tempfile
from collections import deque
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from musicgen.playground import telemetry
from musicgen.playground.state import PlaygroundState

METER_HZ = 30.0
_TMP = Path(tempfile.gettempdir())
_SAMPLE_DIR = _TMP / "musicgen_playground_samples"
_PRESET_DIR = _TMP / "musicgen_playground_presets"
_EXPORT_DIR = _TMP / "musicgen_playground_exports"
# control messages that mutate server-mirrored state -> re-sync every client
_SNAPSHOT_AFTER = {"set_override", "clear_override", "set_mapping", "reset_mapping",
                   "mapping_store", "mapping_recall", "set_console", "transport", "reseed",
                   "set_automation", "seek", "set_dramaturg"}


def _safe_name(name: str) -> str:
    """A filesystem-safe preset stem: no separators, bounded length."""
    return re.sub(r"[^A-Za-z0-9 _-]", "", str(name)).strip()[:64]


def _preset_names() -> list[str]:
    return sorted(p.stem for p in _PRESET_DIR.glob("*.json")) if _PRESET_DIR.is_dir() else []


class Hub:
    """Session singleton: the state, the connected clients, and the loop handle
    the player thread needs to hand telemetry back across the thread boundary."""

    def __init__(self) -> None:
        self.state = PlaygroundState()
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tel_queue: asyncio.Queue | None = None
        self._recent: deque = deque(maxlen=6)  # window for live linting

    def on_bar(self, result) -> None:  # called on the player (generation) thread
        loop, queue = self.loop, self.tel_queue
        if loop is None or queue is None:
            return
        player = self.state.player
        pinned = sorted(player.engine.overrides) if player is not None else []
        mapped = (telemetry.mapped_targets(result.affect, player.engine.config.mapper)
                  if player is not None else {})
        if self._recent and result.bar <= self._recent[-1].bar:
            self._recent.clear()  # engine restarted (bar reset) — drop stale window
        self._recent.append(result)
        meter = player.engine.config.meter if player is not None else None
        lint = telemetry.lint_result(list(self._recent), meter) if meter is not None else None
        msg = telemetry.bar_telemetry(result, pinned, mapped, lint)
        loop.call_soon_threadsafe(queue.put_nowait, msg)

    async def broadcast(self, msg: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


async def _telemetry_pump() -> None:
    assert hub.tel_queue is not None
    while True:
        msg = await hub.tel_queue.get()
        await hub.broadcast(msg)


async def _meter_pump() -> None:
    period = 1.0 / METER_HZ
    while True:
        await asyncio.sleep(period)
        if not hub.state.running:
            continue
        player = hub.state.player
        await hub.broadcast({
            "type": "meter",
            "level": hub.state.level(),
            "cpu": hub.state.cpu(),
            "bars": player.bars_played if player is not None else 0,
        })


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    hub.tel_queue = asyncio.Queue()
    tasks = [asyncio.create_task(_telemetry_pump()), asyncio.create_task(_meter_pump())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        hub.state.stop()


app = FastAPI(title="anoptic-musicgen playground", lifespan=lifespan)


@app.get("/api/schema")
async def api_schema() -> JSONResponse:
    return JSONResponse(telemetry.schema())


@app.get("/api/state")
async def api_state() -> JSONResponse:
    return JSONResponse(hub.state.snapshot())


@app.post("/api/sample")
async def api_sample(file: UploadFile = File(...), root: int = Form(72)) -> JSONResponse:
    """Load an audio file into the sampler ("keys") voice. Validated by trying
    to decode it (libsndfile) before it rebuilds the console."""
    _SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _SAMPLE_DIR / Path(file.filename or "sample.wav").name
    dest.write_bytes(await file.read())
    try:
        import signalflow as sf
        buf = sf.Buffer(str(dest))
        if buf.num_frames <= 0:
            raise ValueError("empty sample")
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        return JSONResponse({"ok": False, "error": f"unreadable audio: {exc}"}, status_code=400)
    hub.state.set_sample(str(dest), int(root))
    await hub.broadcast(hub.state.snapshot())
    return JSONResponse({"ok": True, "name": dest.name,
                         "frames": buf.num_frames, "sample_rate": buf.sample_rate})


@app.post("/api/sample/clear")
async def api_sample_clear() -> JSONResponse:
    hub.state.clear_sample()
    await hub.broadcast(hub.state.snapshot())
    return JSONResponse({"ok": True})


@app.get("/api/presets")
async def api_presets() -> JSONResponse:
    return JSONResponse({"presets": _preset_names()})


@app.post("/api/preset")
async def api_preset_save(payload: dict = Body(...)) -> JSONResponse:
    """Save the full session (seed, affect, overrides, mapping, console,
    automation) under a name — the session snapshot."""
    name = _safe_name(payload.get("name", ""))
    if not name:
        return JSONResponse({"ok": False, "error": "empty preset name"}, status_code=400)
    _PRESET_DIR.mkdir(parents=True, exist_ok=True)
    (_PRESET_DIR / f"{name}.json").write_text(json.dumps(hub.state.export_session(), indent=2))
    return JSONResponse({"ok": True, "name": name, "presets": _preset_names()})


@app.post("/api/preset/load")
async def api_preset_load(payload: dict = Body(...)) -> JSONResponse:
    name = _safe_name(payload.get("name", ""))
    path = _PRESET_DIR / f"{name}.json"
    if not path.is_file():
        return JSONResponse({"ok": False, "error": f"no preset {name!r}"}, status_code=404)
    try:
        hub.state.import_session(json.loads(path.read_text()))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"could not load preset: {exc}"}, status_code=400)
    await hub.broadcast(hub.state.snapshot())
    return JSONResponse({"ok": True})


@app.post("/api/preset/delete")
async def api_preset_delete(payload: dict = Body(...)) -> JSONResponse:
    name = _safe_name(payload.get("name", ""))
    (_PRESET_DIR / f"{name}.json").unlink(missing_ok=True)
    return JSONResponse({"ok": True, "presets": _preset_names()})


@app.get("/api/export")
async def api_export(kind: str = "wav", bars: int = 32):
    """Offline bounce of the current config to WAV or MIDI (download). Requires
    a stopped transport — the live player already owns the one audio graph."""
    # both guards below are checked synchronously (no await between them and the
    # flag set), so a WS `transport start` can't slip a second graph in
    if hub.state.running:
        return JSONResponse({"ok": False, "error": "stop playback before exporting"},
                            status_code=409)
    if hub.state.exporting:
        return JSONResponse({"ok": False, "error": "an export is already in progress"},
                            status_code=409)
    kind = "midi" if kind == "midi" else "wav"
    bars = max(1, min(int(bars), 512))
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    ext = "mid" if kind == "midi" else "wav"
    dest = _EXPORT_DIR / f"musicgen-seed{hub.state.seed}-{bars}bars.{ext}"
    hub.state.exporting = True  # blocks a concurrent transport start (one graph at a time)
    try:
        await asyncio.to_thread(hub.state.render_export, kind, bars, str(dest))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    finally:
        hub.state.exporting = False
    media = "audio/midi" if kind == "midi" else "audio/wav"
    return FileResponse(str(dest), media_type=media, filename=dest.name)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "running": hub.state.running}


def _handle(msg: dict) -> None:
    """Dispatch one inbound control message. Raises on bad input; the caller
    turns that into an error frame for the sender."""
    kind = msg.get("type")
    state = hub.state
    if kind == "set_affect":
        state.set_affect(msg.get("valence"), msg.get("energy"), msg.get("tension"),
                         bool(msg.get("urgent", False)))
    elif kind == "set_override":
        state.set_override(msg["name"], msg["value"])
    elif kind == "clear_override":
        state.clear_override(msg["name"])
    elif kind == "request_key":
        state.request_key(msg["tonic"], bool(msg.get("urgent", False)))
    elif kind == "set_mapping":
        state.set_mapping_field(msg["field"], msg["value"])
    elif kind == "reset_mapping":
        state.reset_mapping()
    elif kind == "mapping_store":
        state.store_mapping(str(msg["slot"]))
    elif kind == "mapping_recall":
        state.recall_mapping(str(msg["slot"]))
    elif kind == "set_console":
        state.set_console_fields(msg["fields"])
    elif kind == "set_dramaturg":
        state.set_dramaturg_fields(msg["fields"])
    elif kind == "reseed":
        state.reseed(msg["seed"])
    elif kind == "set_automation":
        state.set_automation(msg.get("enabled"), msg.get("loop_bars"), msg.get("points"))
    elif kind == "seek":
        state.seek(msg["bar"])
    elif kind == "transport":
        action = msg.get("action")
        if action == "start":
            state.start(hub.on_bar)
        elif action == "stop":
            state.stop()
        else:
            raise ValueError(f"unknown transport action {action!r}")
    else:
        raise ValueError(f"unknown message type {kind!r}")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    hub.clients.add(ws)
    try:
        await ws.send_json(telemetry.schema())
        await ws.send_json(hub.state.snapshot())
        while True:
            try:
                msg = await ws.receive_json()
            except WebSocketDisconnect:
                break
            try:
                _handle(msg)
            except Exception as exc:  # noqa: BLE001
                await ws.send_json({"type": "error", "error": str(exc),
                                    "for": msg.get("type") if isinstance(msg, dict) else None})
                continue
            if isinstance(msg, dict) and msg.get("type") in _SNAPSHOT_AFTER:
                await hub.broadcast(hub.state.snapshot())
    finally:
        hub.clients.discard(ws)


# The React build (Phase 2) drops into web/dist; until then, a hint at root.
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if _WEB_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")
else:
    @app.get("/")
    async def _root() -> HTMLResponse:
        return HTMLResponse(
            "<h1>anoptic-musicgen playground</h1>"
            "<p>API is up. Connect a client to <code>/ws</code>, or build the "
            "<code>web/</code> front-end (Phase 2). Schema at <code>/api/schema</code>.</p>"
        )
