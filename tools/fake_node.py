#!/usr/bin/env python3
"""假节点：在手机 App / 平板 / ESP32 还没做出来之前，往中枢灌假数据，用来调试界面。

两种方式:
  HTTP（默认，和真设备走同一条路）
  MQTT（--mqtt，仅在 broker 开启时用）

用法:
  python tools/fake_node.py --node tablet --name "联想平板" --pct 62 --charging
  python tools/fake_node.py --node iqooz8 --name "iQOO Z8" --pct 87 --per "Lolli ANC:60,W820NB:-"
  python tools/fake_node.py --node tablet --pct 40 --looping 30 --jitter 1
"""
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request


def build(a) -> dict:
    per = []
    if a.per:
        for item in a.per.split(","):
            item = item.strip()
            if not item:
                continue
            name, _, val = item.rpartition(":")
            per.append({
                "id": name.lower().replace(" ", "-"),
                "name": name,
                "pct": None if val in ("-", "", "null", "None") else int(val),
            })
    return {
        "node": a.node,
        "name": a.name or a.node,
        "ts": int(time.time()),
        "battery": {"pct": a.pct, "charging": a.charging, "ac": a.charging},
        "peripherals": per,
    }


def post_http(base: str, payload: dict, token: str) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/report", data=body,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Token", token)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--pct", type=int, default=80)
    ap.add_argument("--charging", action="store_true")
    ap.add_argument("--looping", type=float, default=0, help="每 N 秒重发（0=只发一次）")
    ap.add_argument("--jitter", type=int, default=1)
    ap.add_argument("--per", default="", help='"名字:电量,名字:电量"，电量写 - 表示未知')
    ap.add_argument("--http", default="http://127.0.0.1:8080")
    ap.add_argument("--token", default="")
    ap.add_argument("--mqtt", action="store_true", help="改用 MQTT 上报")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    a = ap.parse_args()

    if a.mqtt:
        import paho.mqtt.client as mqtt
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-{a.node}")
        c.connect(a.host, a.port, 60)
        c.loop_start()
        t0 = time.time()
        while not c.is_connected() and time.time() - t0 < 5:
            time.sleep(0.05)
        c.publish(f"batt/{a.node}/online", "1", qos=1, retain=True)
        while True:
            payload = build(a)
            info = c.publish(f"batt/{a.node}/state",
                             json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
            info.wait_for_publish(timeout=5)
            print(f"mqtt  {a.node} {a.pct}%", flush=True)
            if a.looping <= 0:
                break
            time.sleep(a.looping)
            a.pct = max(0, min(100, a.pct - random.randint(0, a.jitter)))
        time.sleep(0.5)
        c.loop_stop()
        c.disconnect()
        return 0

    while True:
        payload = build(a)
        try:
            resp = post_http(a.http, payload, a.token)
            print(f"http  {a.node} {a.pct}% -> {a.http}/report  {resp}", flush=True)
        except Exception as e:
            print(f"http  {a.node} 失败: {e}", flush=True)
            return 1
        if a.looping <= 0:
            break
        time.sleep(a.looping)
        a.pct = max(0, min(100, a.pct - random.randint(0, a.jitter)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
