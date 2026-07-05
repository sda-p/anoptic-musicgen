"""The FastAPI service: one WebSocket carrying bidirectional control + per-bar
telemetry + a ~30 fps meter, plus REST for the schema/state snapshots. A single
session (one engine + player) is plenty for a local dev tool; multiple browser
tabs just share it and stay in sync via broadcast snapshots.

Threading: the player runs the engine on its own daemon thread and calls
on_bar there; we marshal each telemetry dict onto the asyncio loop with
call_soon_threadsafe. The meter is read (get_value on a follower) directly from
the loop — a benign cross-thread scalar read.
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from musicgen.playground import telemetry
from musicgen.playground.state import PlaygroundState

METER_HZ = 30.0
# control messages that mutate server-mirrored state -> re-sync every client
_SNAPSHOT_AFTER = {"set_override", "clear_override", "set_mapping", "transport", "reseed"}


class Hub:
    """Session singleton: the state, the connected clients, and the loop handle
    the player thread needs to hand telemetry back across the thread boundary."""

    def __init__(self) -> None:
        self.state = PlaygroundState()
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tel_queue: asyncio.Queue | None = None

    def on_bar(self, result) -> None:  # called on the player (generation) thread
        loop, queue = self.loop, self.tel_queue
        if loop is None or queue is None:
            return
        player = self.state.player
        pinned = sorted(player.engine.overrides) if player is not None else []
        mapped = (telemetry.mapped_targets(result.affect, player.engine.config.mapper)
                  if player is not None else {})
        msg = telemetry.bar_telemetry(result, pinned, mapped)
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
    elif kind == "reseed":
        state.reseed(msg["seed"])
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
