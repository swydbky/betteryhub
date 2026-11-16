#!/usr/bin/env python3
"""battery-hub —— 电量汇聚中枢（Windows 常驻）

传输层：HTTP（不再依赖 MQTT broker）
  设备 → hub : POST /report   自己的电量（变化或翻转时立即发，平时 10 分钟心跳）
  hub → 设备 : GET  /state    全网快照；小组件/ESP32 按自己的节奏取

为什么不用 MQTT：
  实测 amqtt（纯 Python broker）存在**会话静默死亡**——TCP 仍 Established、
  但订阅者再也收不到消息（新订阅者却能收到 retained）。这类问题在 24/7 场景不可接受。
  HTTP 方案少一个进程、少一个协议实现、少一类故障，且对 ESP32 / Android 都更简单。
  MQTT 代码保留在 mqtt_bridge 里，配置里 mqtt.enabled=true 可开启，用于以后接别的设备。

持久化：状态写入 state.json，重启后不丢（等价于 MQTT 的 retained）。

用法:
  python hub/hub.py --once      # 只打印本机电量
  python hub/hub.py             # 常驻
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import battery

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "state.json")

DEFAULT_CONF = {
    "node": {"id": "pc", "name": "Win10 笔电"},
    "publish": {"heartbeat_sec": 600, "min_delta_pct": 1},
    "http": {"bind": "0.0.0.0", "port": 18080, "token": ""},
    "mqtt": {"enabled": False, "host": "127.0.0.1", "port": 1883,
             "username": "", "password": ""},
    # 节点显示名覆盖：设备自己报的机型名太长时，在这里改成短名
    "aliases": {},
}

NODES: dict[str, dict] = {}
# 节点显示名覆盖（config.json 的 aliases）
ALIASES: dict[str, str] = {}
# 外设注册表：id -> {id,name,pct,connected,node,seen}
# 规则：谁最后把它报成"已连接"，它就固定挂在那台设备下面（耳机在手机/平板间切换时自动搬家）
PERIPH: dict[str, dict] = {}
LOCK = threading.Lock()
START_TS = time.time()
DIRTY = threading.Event()


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def deep_update(base: dict, over: dict) -> dict:
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_conf(path: str) -> dict:
    conf = json.loads(json.dumps(DEFAULT_CONF))
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            deep_update(conf, json.load(f))
    return conf


# --------------------------------------------------------------------------- 状态
def load_store() -> None:
    if not os.path.isfile(STORE):
        return
    try:
        data = json.load(open(STORE, encoding="utf-8"))
        now = time.time()
        legacy = "nodes" not in data
        nodes = data if legacy else data.get("nodes", {})
        per = {} if legacy else data.get("periph", {})
        for nid, rec in nodes.items():
            rec["online"] = False
            rec["seen"] = min(float(rec.get("seen", 0)), now)
            NODES[nid] = rec
        for pid, p in per.items():
            PERIPH[pid] = p
        log(f"从 state.json 恢复 {len(NODES)} 个节点 / {len(PERIPH)} 个外设（均标记离线）")
    except Exception as e:
        log(f"state.json 读不了: {e}")


def save_store() -> None:
    tmp = STORE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"nodes": NODES, "periph": PERIPH}, f, ensure_ascii=False)
        os.replace(tmp, STORE)
    except Exception as e:
        log(f"state.json 写失败: {e}")


def writer_loop(stop: threading.Event) -> None:
    while not stop.wait(2):
        if DIRTY.is_set():
            DIRTY.clear()
            with LOCK:
                save_store()


def update_node(payload: dict) -> None:
    nid = str(payload.get("node") or "").strip()
    if not nid or len(nid) > 40:
        raise ValueError("node 字段非法")
    batt = payload.get("battery") or {}
    pct = batt.get("pct")
    if pct is not None:
        pct = int(pct)
        if not 0 <= pct <= 100:
            raise ValueError("pct 超出 0..100")
    per = payload.get("peripherals") or []
    if not isinstance(per, list):
        raise ValueError("peripherals 必须是数组")
    now = time.time()
    rec = {
        "state": {
            "node": nid,
            "name": payload.get("name") or nid,
            "ts": int(payload.get("ts") or now),
            "battery": {
                "pct": pct,
                "charging": batt.get("charging"),
                "ac": batt.get("ac"),
            },
        },
        "online": True,
        "seen": now,
    }
    with LOCK:
        NODES[nid] = rec
        for p in per:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or "").strip()
            if not pid:
                continue
            name = str(p.get("name") or pid)
            ppct = p.get("pct")
            ppct = None if ppct is None else int(ppct)
            conn = bool(p.get("connected", ppct is not None))
            cur = PERIPH.get(pid)
            pcls = p.get("cls")
            pcls = -1 if pcls is None else int(pcls)
            if conn:
                # 谁最后报"已连接"，归属就搬到谁那里（耳机换设备）
                PERIPH[pid] = {"id": pid, "name": name, "pct": ppct, "cls": pcls,
                               "connected": True, "node": nid, "seen": now}
            elif cur is not None and cur.get("node") == nid:
                # 同一台设备报"已断开"：保留最后的电量，只改状态
                cur["name"] = name
                if ppct is not None:
                    cur["pct"] = ppct
                if pcls >= 0:
                    cur["cls"] = pcls
                cur["connected"] = False
                cur["seen"] = now
            elif cur is None:
                # 配对表里从没测到过电量的设备：占位显示 "—"，不隐藏
                PERIPH[pid] = {"id": pid, "name": name, "pct": ppct, "cls": pcls,
                               "connected": False, "node": nid, "seen": now}
    DIRTY.set()


def snapshot_locked() -> dict:
    now = time.time()
    per_by_node: dict[str, list] = {}
    for pid, p in PERIPH.items():
        age = int(now - p.get("seen", now))
        # 超过 7 天没再出现（大概率已解绑）才丢弃；其余全显示
        if age > 7 * 86400 and not p.get("connected"):
            continue
        per_by_node.setdefault(p.get("node", ""), []).append({
            "id": pid, "name": p.get("name", pid), "pct": p.get("pct"),
            "cls": p.get("cls", -1),
            "connected": bool(p.get("connected")), "age_sec": age,
        })
    for lst in per_by_node.values():
        lst.sort(key=lambda x: (not x["connected"], x["name"]))

    out = []
    for nid, rec in NODES.items():
        st = rec.get("state") or {}
        out.append({
            "node": nid,
            "name": ALIASES.get(nid) or st.get("name", nid),
            "online": rec["online"],
            "age_sec": int(now - rec["seen"]) if rec.get("seen") else None,
            "battery": st.get("battery", {"pct": None, "charging": None, "ac": None}),
            "peripherals": per_by_node.get(nid, []),
            "ts": st.get("ts"),
        })
    out.sort(key=lambda x: (not x["online"], x["node"]))
    return {"hub_ts": int(now), "count": len(out), "nodes": out}


def reaper_loop(conf: dict, stop: threading.Event) -> None:
    limit = max(3 * int(conf["publish"]["heartbeat_sec"]), 1800)
    while not stop.wait(30):
        now = time.time()
        with LOCK:
            for nid, rec in NODES.items():
                if rec["online"] and (now - rec["seen"]) > limit:
                    rec["online"] = False
                    DIRTY.set()
                    log(f"{nid} 超过 {limit}s 无上报，标记离线")


# --------------------------------------------------------------------------- 本机采集
def publisher_loop(conf: dict, stop: threading.Event) -> None:
    node = conf["node"]
    hb = int(conf["publish"]["heartbeat_sec"])
    delta = int(conf["publish"]["min_delta_pct"])
    last, last_pub = None, 0.0
    while not stop.wait(5):
        b = battery.read()
        now = time.time()
        changed = (
            last is None
            or (b["pct"] is not None and last["pct"] is not None
                and abs(b["pct"] - last["pct"]) >= delta)
            or (b["pct"] is None) != (last["pct"] is None)
            or b["charging"] != last["charging"]
            or b["ac"] != last["ac"]
        )
        if changed or (now - last_pub) >= hb:
            update_node({
                "node": node["id"], "name": node["name"],
                "battery": {"pct": b["pct"], "charging": b["charging"], "ac": b["ac"]},
                "peripherals": [],
            })
            if last is not None:
                log(f"发布[{'变化' if changed else '心跳'}] {b['pct']}% "
                    f"charging={b['charging']} ac={b['ac']}")
            last, last_pub = b, now


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "battery-hub/0.2"
    conf: dict = {}

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path.startswith("/state"):
            with LOCK:
                snap = snapshot_locked()
            self._json(snap)
        elif self.path.startswith("/health"):
            self._json({"ok": True, "uptime": int(time.time() - START_TS),
                        "nodes": len(NODES)})
        elif self.path.startswith("/apk"):
            # 方便设备自己在浏览器里下载新版 APK，省得每次插线
            apk = os.path.join(ROOT, "android", "out", "probe.apk")
            if not os.path.isfile(apk):
                self.send_error(404, "apk not built")
                return
            self._send(200, open(apk, "rb").read(),
                       "application/vnd.android.package-archive")
        elif self.path in ("/", "/index.html"):
            try:
                body = open(os.path.join(HERE, "dashboard.html"), "rb").read()
            except OSError:
                self.send_error(404)
                return
            self._send(200, body, "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.path.startswith("/report"):
            self.send_error(404)
            return
        token = self.conf.get("http", {}).get("token") or ""
        if token and self.headers.get("X-Token") != token:
            self._json({"ok": False, "err": "bad token"}, 401)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 64 * 1024:
                raise ValueError("body 长度非法")
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            update_node(payload)
            self._json({"ok": True})
        except Exception as e:
            self._json({"ok": False, "err": str(e)}, 400)

    def log_message(self, fmt, *args):
        pass


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def ipv6_addr() -> str:
    """取本机第一个全局 IPv6（用于打印提示，不参与逻辑）。"""
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
            a = info[4][0].split("%")[0]
            if not a.startswith("fe80") and not a.startswith("::"):
                return a
    except Exception:
        pass
    return "::"


# --------------------------------------------------------------------------- 可选 MQTT
def mqtt_bridge(conf: dict, stop: threading.Event) -> None:
    """把 HTTP 的状态同步到 MQTT（默认关闭，留给以后接别的生态）。"""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        log("未安装 paho-mqtt，跳过 MQTT 桥")
        return
    m = conf["mqtt"]
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"hub-{os.getpid()}")
    if m.get("username"):
        c.username_pw_set(m["username"], m["password"])

    def on_connect(cl, u, f, rc, p=None):
        if rc == 0:
            log(f"MQTT 桥已连 {m['host']}:{m['port']}")

    c.on_connect = on_connect
    try:
        c.connect(m["host"], int(m["port"]), 60)
        c.loop_start()
    except OSError as e:
        log(f"MQTT 桥连接失败（不影响 HTTP）: {e}")
        return
    last = {}
    while not stop.wait(5):
        with LOCK:
            items = [(nid, dict(rec["state"])) for nid, rec in NODES.items() if rec.get("state")]
        for nid, st in items:
            key = (st.get("battery", {}).get("pct"), st.get("battery", {}).get("charging"))
            if last.get(nid) != key:
                c.publish(f"batt/{nid}/state", json.dumps(st, ensure_ascii=False),
                          qos=1, retain=True)
                last[nid] = key
    c.loop_stop()


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default=os.path.join(ROOT, "config.json"))
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    if args.once:
        print(json.dumps(battery.read(), ensure_ascii=False))
        return 0

    conf = load_conf(args.config)
    global ALIASES
    ALIASES = dict(conf.get("aliases") or {})
    node = conf["node"]
    Handler.conf = conf
    load_store()

    stop = threading.Event()
    threading.Thread(target=publisher_loop, args=(conf, stop), daemon=True).start()
    threading.Thread(target=reaper_loop, args=(conf, stop), daemon=True).start()
    threading.Thread(target=writer_loop, args=(stop,), daemon=True).start()
    if conf["mqtt"].get("enabled"):
        threading.Thread(target=mqtt_bridge, args=(conf, stop), daemon=True).start()

    # 开机先把自己报一次，面板立刻有东西
    b = battery.read()
    update_node({"node": node["id"], "name": node["name"],
                 "battery": {"pct": b["pct"], "charging": b["charging"], "ac": b["ac"]},
                 "peripherals": []})

    h = conf["http"]
    srv = ThreadingHTTPServer((h["bind"], int(h["port"])), Handler)

    # 校园网 IPv4 的代理 ARP 有时不给你代答（例如平板访问电脑），但 IPv6 是通的，
    # 所以额外开一个 IPv6 监听，让每台设备自己挑能连的地址。
    srv6 = None
    try:
        class _V6(ThreadingHTTPServer):
            address_family = socket.AF_INET6

        srv6 = _V6(("::", int(h["port"])), Handler)
        threading.Thread(target=srv6.serve_forever, daemon=True).start()
    except Exception as e:
        log(f"IPv6 监听失败（不影响 IPv4）: {e}")

    log(f"节点 {node['id']} ({node['name']}) · {b['pct']}%")
    log(f"面板   http://{lan_ip()}:{h['port']}/")
    if srv6:
        log(f"       http://[{ipv6_addr()}]:{h['port']}/   (IPv6)")
    log(f"上报   POST http://{lan_ip()}:{h['port']}/report")
    log("传输层 HTTP · MQTT " + ("已启用" if conf["mqtt"].get("enabled") else "未启用"))

    def bye(*_):
        log("收到退出信号")
        stop.set()
        with LOCK:
            save_store()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, bye)
    signal.signal(signal.SIGTERM, bye)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        bye()
    return 0


if __name__ == "__main__":
    sys.exit(main())
