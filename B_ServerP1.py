#!/usr/bin/env python3
# B_server.py  - RasPi の物理ボタン → G_server へ送信するクライアント

import asyncio
import json
import time

import aiohttp
import websockets

import grovepi
from grove_rgb_lcd import setText, setRGB

# =====================================
# 設定（★ここを自分の環境に合わせて変更）
# =====================================

# G_server.py を動かしている PC の IP アドレス or ホスト名
G_SERVER_HOST = "10.77.98.125"      # ← ここを直す！
G_SERVER_PORT = 8000                # G_server.py のポート

# この RasPi が担当するプレイヤー番号
PLAYER_NO = 1

# GrovePi のポート設定（元コードから移植）:contentReference[oaicite:3]{index=3}
ULTRASONIC_PORT = 2    # D2
LED_PORT        = 7    # D7
DIAL_PORT       = 0    # A0
LIGHT_PORT      = 1    # A1
BUTTON_PORT     = 2    # A2 (アナログ読み)

LOOP_HZ = 0.01         # ループ周期(秒)


# =====================================
# G_server から WS URL を取得
# =====================================

async def fetch_ws_url(name: str = "raspi-button") -> str:
    """
    G_server の /getplayer に POST して
    この RasPi 用の WebSocket URL をもらう。
    """
    url = f"http://{G_SERVER_HOST}:{G_SERVER_PORT}/getplayer"
    payload = {"name": name}
    print(f"[HTTP] POST {url} {payload}")

    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            print("[HTTP] response:", data)

    if not data.get("ok"):
        raise RuntimeError("getplayer returned ok=False")

    ws_url = data["ws_url"]
    print(f"[HTTP] ws_url = {ws_url}")
    return ws_url


# =====================================
# WebSocket 送信（ボタン押下イベント）
# =====================================

async def send_press(ws: websockets.WebSocketClientProtocol, player: int):
    """
    ボタンを押した（正確にはカウントアップした）タイミングで
    G_server に JSON を送信。
    G_server 側仕様に合わせて type='press', player=番号 :contentReference[oaicite:4]{index=4}
    """
    msg = {
        "type": "press",
        "player": player,
    }
    text = json.dumps(msg)
    print("[WS] send:", text)
    await ws.send(text)


# =====================================
# GrovePi + LCD の初期化
# =====================================

def init_hardware():
    print("[HW] Init GrovePi ports")
    grovepi.pinMode(LED_PORT, "OUTPUT")
    # 超音波・アナログポートは特に pinMode 指定不要

    setRGB(0, 0, 0)
    setText("Ready...")


# =====================================
# ボタン & センサー ループ
# =====================================

async def button_loop(ws: websockets.WebSocketClientProtocol):
    """
    RasPi 側のメインループ。
    - ボタンの状態を見る
    - センサー値を読む
    - LCD 表示を更新
    - 必要なら send_press() を呼んで G_server へ送信
    """

    init_hardware()

    count = 0
    push_time = 0
    count_flag = False
    reset_flag = False
    prev_pressed = False

    while True:
        try:
            # --- ボタン状態の取得（元コードのしきい値ロジック）:contentReference[oaicite:5]{index=5}
            push_val = grovepi.analogRead(BUTTON_PORT)
            if push_val != 0 and (push_val % 1022 > 1010 or push_val % 1022 < 10):
                pressed = True
            else:
                pressed = False

            # --- 各種センサー
            #usrange = grovepi.ultrasonicRead(ULTRASONIC_PORT)
            #light_val = grovepi.analogRead(LIGHT_PORT)
            #dial_val = grovepi.analogRead(DIAL_PORT)

            # --- 押しっぱなし処理（長押し検出など）
            if pressed:
                push_time += 1

                if not count_flag:
                    # 押し始め直後の表示
                    setText("Pushed Button!!!")
                    count_flag = True

                # 簡易カウントダウン表示（元コードテイスト）
                if not reset_flag:
                    if push_time % 40 == 0:
                        setText("Pushed!! reset=3")
                    elif push_time % 50 == 0:
                        setText("Pushed!! reset=2")
                    elif push_time % 60 == 0:
                        setText("Pushed!! reset=1")
                    elif push_time % 70 == 0:
                        reset_flag = True
                        setText("Reset (*^ ^)/")
                        count = -1  # 次のインクリメントで 0 に戻る

            # --- 離したタイミング（立ち下がりエッジ）
            if (not pressed) and prev_pressed:
                # カウントアップ
                count += 1
                count_flag = False
                reset_flag = False
                push_time = 0

                # LED の色を変えてみる
                color = (count * 10) % 256
                setRGB(color, color, color)

                # LCD にステータス表示
                text = "cnt={0}".format(count)
                setText(text)

                # ★ここが一番大事：G_server へ送信！
                await send_press(ws, PLAYER_NO)

            # 状態保存
            prev_pressed = pressed

            # 少し待つ（asyncio版）
            #await asyncio.sleep(LOOP_HZ)

        except KeyboardInterrupt:
            print("[HW] KeyboardInterrupt, cleaning up...")
            grovepi.digitalWrite(LED_PORT, 0)
            setRGB(0, 0, 0)
            break
        except IOError:
            # センサー通信エラー時
            print("[HW] IOError (sensor error)")
            await asyncio.sleep(0.1)
        except websockets.ConnectionClosed:
            # サーバとの接続が切れたらループ終了して再接続へ
            print("[WS] connection closed, leaving button_loop()")
            raise


# =====================================
# メイン：再接続付きで ws につなぎ続ける
# =====================================

async def main():
    while True:
        try:
            ws_url = await fetch_ws_url()
            print(f"[WS] connecting to {ws_url}")

            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                print("[WS] connected!")
                # サーバからのメッセージは今回は特に使わないので、
                # button_loop の中で送信だけ行う。
                await button_loop(ws)

        except Exception as e:
            print(f"[ERR] {e!r} -> 3秒後に再試行")
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bye.")
