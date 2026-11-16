#!/usr/bin/env python3
"""【备选，默认不启用】内嵌 MQTT broker（amqtt 0.12，纯 Python）

当前主链路已经改成 HTTP（见 hub.py 顶部说明），本文件保留是为了将来接别的 MQTT 生态。
若要启用：`config.json` 里把 `mqtt.enabled` 设为 true，然后 `python hub/broker.py`，
hub.py 会自动把状态桥接到 `batt/<node>/state`。

已知问题（当初放弃它的原因）：
  amqtt 跑十分钟左右会出现**会话静默死亡**——TCP 仍 Established，但订阅者再也收不到消息
  （新订阅者却能收到 retained）。仅适合短时调试，不要用于 24/7。

为什么当初不用 Mosquitto：
  Windows 安装包需要管理员权限装系统服务，且本机从 mosquitto.org 下载实测卡死
  （0 字节 / 10 秒不增长）。

用法:
  python hub/broker.py                 # 0.0.0.0:1883
  python hub/broker.py --bind 0.0.0.0:1883
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from amqtt.broker import Broker

CONFIG = {
    "listeners": {
        "default": {
            "type": "tcp",
            "bind": "0.0.0.0:1883",
            "max_connections": 64,
        }
    },
    "sys_interval": 0,
    "topic_check": {"enabled": False},
    "plugins": {
        # M1 开发期允许匿名；接入手机前改成 False 并配置密码插件
        "amqtt.plugins.authentication.AnonymousAuthPlugin": {
            "allow_anonymous": True,
        },
    },
}


async def run(bind: str) -> None:
    CONFIG["listeners"]["default"]["bind"] = bind
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    broker = Broker(CONFIG)
    await broker.start()
    print(f"[broker] amqtt 已启动，监听 {bind}（匿名）", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        print("[broker] 正在关闭…", flush=True)
        await broker.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="0.0.0.0:1883")
    a = ap.parse_args()
    try:
        asyncio.run(run(a.bind))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
