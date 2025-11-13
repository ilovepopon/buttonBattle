# g_server.py
import asyncio, json, uuid, pathlib
from aiohttp import web

BASE = pathlib.Path(__file__).parent

PLAYERS = {"p1": 0, "p2": 0}
TIME_LEFT = 10
PHASE = "idle"   # idle / playing / finished

WS_CLIENTS = set()   # battle 1.html 用
WS_BUTTONS = set()   # B_server 用

# --- static: battle 1.html を返す ---
async def battle_page(req):
    return web.FileResponse("battle 1.html")

# --- /getplayer: B_server が叩く。WS URL を返す ---
async def getplayer(req):
    body = await req.json()
    name = (body.get("name") or "noname").strip()
    token = str(uuid.uuid4())
    host = req.host
    ws_url = f"ws://{host}/ws?token={token}&role=button"
    return web.json_response({"ok": True, "ws_url": ws_url, "token": token, "name": name})

async def broadcast_state():
    msg = json.dumps({
        "type": "state",
        "p1": PLAYERS["p1"],
        "p2": PLAYERS["p2"],
        "time": TIME_LEFT,
        "phase": PHASE,
    })
    for ws in list(WS_CLIENTS | WS_BUTTONS):
        if not ws.closed:
            await ws.send_str(msg)

async def game_loop():
    global TIME_LEFT, PHASE
    while True:
        if PHASE == "playing":
            await asyncio.sleep(1)
            TIME_LEFT -= 1
            if TIME_LEFT <= 0:
                PHASE = "finished"
            await broadcast_state()
        else:
            await asyncio.sleep(0.1)

# --- WebSocket /ws ---
async def ws_handler(req):
    role = req.query.get("role", "client")  # client or button
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(req)

    if role == "button":
        WS_BUTTONS.add(ws)
    else:
        WS_CLIENTS.add(ws)

    await broadcast_state()

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)

            t = data.get("type")
            if t == "start":
                # battle 1.html から「スタート」ボタンが押された
                global TIME_LEFT, PHASE
                PLAYERS["p1"] = PLAYERS["p2"] = 0
                TIME_LEFT = 10
                PHASE = "playing"
                await broadcast_state()

            elif t == "press":
                # B_server 側からの押下
                if PHASE != "playing":
                    continue
                if data.get("player") == 1:
                    PLAYERS["p1"] += 1
                elif data.get("player") == 2:
                    PLAYERS["p2"] += 1
                await broadcast_state()

            elif t == "reset":
                PLAYERS["p1"] = PLAYERS["p2"] = 0
                TIME_LEFT = 10
                PHASE = "idle"
                await broadcast_state()
    finally:
        WS_CLIENTS.discard(ws)
        WS_BUTTONS.discard(ws)

    return ws

async def index():
    return web.FileResponse("battle 1.html")
# ---- HTTPサーバ起動 ----
async def start_http():
    app = web.Application()
    app.router.add_get("/", index)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 80)
    await site.start()
    print("[HTTP] on :80")

async def main():
    app = web.Application()
    app.router.add_get("/battle", battle_page)
    app.router.add_post("/getplayer", getplayer)
    app.router.add_get("/ws", ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8000)
    await site.start()
    print("[G] on :8000")

    await asyncio.gather(
        game_loop(),
        asyncio.Event().wait(),
    )

if __name__ == "__main__":
    asyncio.run(main())
