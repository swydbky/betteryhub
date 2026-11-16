#!/usr/bin/env python3
"""PC 桌面悬浮窗 —— 电量中枢的 Windows 挂件

交互（自绘标题栏，不占任务栏）
  * 右上角 ─   最小化：整个面板收成一条 30px 高的横条
  * 右上角 ✕   完全关闭
  * 折叠状态下点条身  → 展开
  * 拖动标题栏 → 移动；位置记在 ui/window.json
  * 右下角斜纹 → 拖拽调宽（260~560）
  * 双击      → 打开网页面板（右键菜单里也有）
  * 不进任务栏：overrideredirect + -toolwindow，Alt+Tab 里也不出现

关于 DPI
  Windows 125% 缩放下 Tk 会把磅值字体放大 1.25 倍而像素坐标不动，导致文字重叠。
  现在所有坐标与字号统一乘 DPI 因子，字号用负值（Tk 约定：负数 = 像素）。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "window.json")

BG = "#0b0f17"
CARD = "#151c29"
CARD_OFF = "#11161f"
BORDER = "#232d3f"
TXT = "#e8eefc"
MUT = "#8fa0bb"
PER = "#c2cee2"
PER_VAL = "#eaf1ff"
PER_OFF = "#59657a"    # 断开的外设：明显变灰
DIM = "#5c6a80"
ACC_A = "#22d3ee"
LOW_A = "#f59e0b"
AMBER = "#fbbf24"
GREEN = "#34d399"

FONT_CN = "Microsoft YaHei UI"
FONT_EN = "Segoe UI"

W_DEFAULT = 320
W_MIN, W_MAX = 260, 560
PAD = 10
GAP = 7
TITLE_H = 26
COLLAPSED_H = 30
GRIP = 14


def get_dpi_scale() -> float:
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


def enable_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def round_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def bolt(c: tk.Canvas, x, y, s, color=AMBER):
    pts = [x + 5 * s, y, x + 1 * s, y + 6.5 * s, x + 4 * s, y + 6.5 * s,
           x + 1.8 * s, y + 12 * s, x + 7.5 * s, y + 5 * s, x + 4.5 * s, y + 5 * s]
    c.create_polygon(pts, fill=color, outline="")


def ago(sec):
    if sec is None:
        return "未知"
    if sec < 60:
        return f"{sec} 秒前"
    if sec < 3600:
        return f"{sec // 60} 分钟前"
    if sec < 86400:
        return f"{sec // 3600} 小时前"
    return f"{sec // 86400} 天前"


# ---------------------------------------------------------------- 类型识别 + 矢量图标
_TYPE_RULES = [
    ("phone",  ("iqoo", "phone", "手机", "iphone", "pixel", "红米", "小米", "荣耀", "一加", "oppo", "vivo", "魅族", "realme")),
    ("laptop", ("笔电", "笔记本", "win10", "win11", "pc", "电脑", "laptop", "macbook", "thinkpad")),
    ("tablet", ("平板", "pad", "ipad", "tablet", "matepad", "mi pad")),
    # 头戴式先判（W820 这类大耳），剩下的才落到小耳机
    ("headphone", ("头戴", "headphone", "w820", "wh-", "hd4", "大耳", "studio", "over-ear")),
    ("earbuds",   ("耳机", "buds", "airpods", "tws", "earbud", "anc", "lolli", "freebuds", " beats ")),
    ("kb",     ("键盘", "keyboard", "thinkplus", "k380", "mx keys")),
    ("mouse",  ("鼠标", "mouse", "mx master", "anywhere")),
]


def icon_from_class(cls) -> str | None:
    """按蓝牙设备类判断类型（比名字可靠）。返回 None 表示认不出来。"""
    try:
        c = int(cls)
    except (TypeError, ValueError):
        return None
    if c <= 0:
        return None
    major = c & 0x1F00
    minor = c & 0x00FC
    if major == 0x0500:                     # 外设
        if minor == 0x40:
            return "kb"
        if minor == 0x80:
            return "mouse"
        if minor == 0xC0:
            return "kb"                     # 键鼠一体，先当键盘
        return None
    if major == 0x0400:                     # 音频
        return "audio"                      # 具体头戴/豆式再按名字细分
    if major == 0x0100:
        return "laptop"
    if major == 0x0200:
        return "phone"
    if major == 0x0700:
        return "audio"
    return None


def icon_kind(name: str, ident: str = "", cls=-1) -> str:
    kind = icon_from_class(cls)
    s = f"{name or ''} {ident or ''}".lower()
    if kind == "audio":
        # 蓝牙类分不出头戴和豆式，用名字关键词补一刀
        if any(k in s for k in ("buds", "airpods", "tws", "earbud", "豆", "anc",
                                "lolli", "freebuds", "耳机")):
            return "earbuds"
        return "headphone"
    if kind:
        return kind
    for k, keys in _TYPE_RULES:
        for kw in keys:
            if kw in s:
                return k
    # BLE 外设常常没有 classic class（cls=-1），用型号前缀兜底：
    # 联想等厂家的 K### 是键盘、M### 是鼠标
    import re
    if re.search(r"\bk\d{3}\b", s):
        return "kb"
    if re.search(r"\bm\d{3}\b", s):
        return "mouse"
    return "generic"


def draw_icon(c: tk.Canvas, kind: str, x: float, cy: float, s: float, color: str, lw: float):
    """在 (x, cy) 画一个宽高约 s 的矢量图标；返回占用宽度。"""
    w = lw
    h = s * 0.86
    y0 = cy - h / 2
    x0 = x

    def rr(a, b, cc, d, r):
        round_rect(c, a, b, cc, d, r, fill="", outline=color, width=w)

    if kind == "phone":
        rr(x0 + s * 0.22, y0, x0 + s * 0.78, y0 + h, s * 0.10)
        c.create_line(x0 + s * 0.42, y0 + h - s * 0.10, x0 + s * 0.58, y0 + h - s * 0.10,
                      fill=color, width=w)
        return s * 0.78
    if kind == "laptop":
        rr(x0 + s * 0.12, y0, x0 + s * 0.88, y0 + h * 0.66, s * 0.06)
        c.create_line(x0, y0 + h * 0.86, x0 + s, y0 + h * 0.86, fill=color, width=w)
        return s
    if kind == "tablet":
        # 横向平板，和竖着的手机区分开
        tw = s * 1.12
        th = h * 0.76
        ty = cy - th / 2
        round_rect(c, x0, ty, x0 + tw, ty + th, s * 0.10, fill="", outline=color, width=w)
        return tw
    if kind == "headphone":
        # 头戴式：大弧 + 两侧耳罩
        c.create_arc(x0 + s * 0.02, y0 - h * 0.06, x0 + s * 0.98, y0 + h * 0.88,
                     start=0, extent=180, style="arc", outline=color, width=w)
        c.create_rectangle(x0 + s * 0.00, y0 + h * 0.46, x0 + s * 0.24, y0 + h * 0.90,
                           fill=color, outline="")
        c.create_rectangle(x0 + s * 0.76, y0 + h * 0.46, x0 + s * 1.00, y0 + h * 0.90,
                           fill=color, outline="")
        return s
    if kind == "earbuds":
        # 真无线：两颗小豆子 + 短柄
        for cx in (x0 + s * 0.28, x0 + s * 0.72):
            c.create_oval(cx - s * 0.13, y0 + h * 0.10, cx + s * 0.13, y0 + h * 0.42,
                          fill="", outline=color, width=w)
            c.create_line(cx, y0 + h * 0.40, cx, y0 + h * 0.92,
                          fill=color, width=w)
        return s
    if kind == "kb":
        rr(x0, y0 + h * 0.18, x0 + s, y0 + h * 0.86, s * 0.10)
        for i in range(3):
            c.create_line(x0 + s * (0.18 + i * 0.28), y0 + h * 0.52,
                          x0 + s * (0.30 + i * 0.28), y0 + h * 0.52, fill=color, width=w)
        return s
    if kind == "mouse":
        rr(x0 + s * 0.22, y0, x0 + s * 0.78, y0 + h, s * 0.22)
        c.create_line(x0 + s * 0.50, y0 + s * 0.02, x0 + s * 0.50, y0 + h * 0.30,
                      fill=color, width=w)
        return s * 0.78
    # generic：小圆环
    c.create_oval(x0 + s * 0.25, cy - s * 0.22, x0 + s * 0.75, cy + s * 0.22,
                  outline=color, width=w)
    return s * 0.75


class Widget:
    def __init__(self, url: str, interval: int):
        self.url = url.rstrip("/")
        self.interval = interval
        self.data = None
        self.error = None
        self.last_ok = 0.0
        self.collapsed = False
        self.wl = W_DEFAULT           # 逻辑宽度
        self.h_px = 100
        self.q: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        self._hit: list = []          # [(x1,y1,x2,y2,action)]
        self._pending = None
        self._drag = None
        self._resize = None
        self._moved = False

        self.s = get_dpi_scale()

        self.root = tk.Tk()
        self.root.title("battery-hub-widget")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-toolwindow", True)   # 不进任务栏 / Alt+Tab
        except Exception:
            pass
        try:
            self.root.attributes("-alpha", 0.96)
        except Exception:
            pass
        self.root.configure(bg=BG)

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=1,
                                highlightbackground=BORDER, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: webbrowser.open(self.url + "/"))
        self.canvas.bind("<Button-3>", self.on_menu)
        self.canvas.bind("<Motion>", self.on_motion)

        self.menu = tk.Menu(self.root, tearoff=0, bg="#1a2230", fg=TXT,
                            activebackground="#3b82f6", activeforeground="#fff", bd=0)
        self.menu.add_command(label="折叠 / 展开", command=self.toggle_collapse)
        self.menu.add_command(label="刷新", command=self.force_refresh)
        self.menu.add_command(label="打开网页面板", command=lambda: webbrowser.open(self.url + "/"))
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.quit)

        self.restore_pos()
        threading.Thread(target=self.poll_loop, daemon=True).start()
        self.root.after(100, self.drain)
        self.root.after(50, self.render)

    # ------------------------------------------------------------------ 工具
    def X(self, v: float) -> int:
        return int(round(v * self.s))

    @property
    def W(self) -> int:
        return self.X(self.wl)

    def F(self, px: float, bold=False):
        return (FONT_CN, -self.X(px), "bold") if bold else (FONT_CN, -self.X(px))

    def FN(self, px: float, bold=False):
        return (FONT_EN, -self.X(px), "bold") if bold else (FONT_EN, -self.X(px))

    # ------------------------------------------------------------------ 网络
    def poll_loop(self):
        while not self.stop.is_set():
            self._one_shot()
            self.stop.wait(self.interval)

    def _one_shot(self):
        try:
            req = urllib.request.Request(self.url + "/state",
                                         headers={"Cache-Control": "no-store"})
            with urllib.request.urlopen(req, timeout=4) as r:
                self.q.put(("ok", json.loads(r.read().decode("utf-8"))))
        except Exception as e:
            self.q.put(("err", str(e)))

    def force_refresh(self):
        threading.Thread(target=self._one_shot, daemon=True).start()

    def drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "ok":
                    self.data, self.error = payload, None
                    self.last_ok = time.time()
                else:
                    self.error = payload
                self.render()
        except queue.Empty:
            pass
        self.root.after(300, self.drain)

    # ------------------------------------------------------------------ 交互
    def _hit_test(self, x, y):
        for (x1, y1, x2, y2, act) in self._hit:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return act
        return None

    def on_press(self, e):
        self._moved = False
        self._pending = self._hit_test(e.x, e.y)
        if self._pending:
            return
        if not self.collapsed and e.x >= self.W - self.X(GRIP) and e.y >= self.h_px - self.X(GRIP):
            self._resize = (e.x_root, self.wl)
            return
        # 折叠/展开状态下都能拖
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())

    def on_drag(self, e):
        if self._resize:
            x0, w0 = self._resize
            new_w = w0 + (e.x_root - x0) / self.s
            new_w = max(W_MIN, min(W_MAX, new_w))
            if abs(new_w - self.wl) >= 2:
                self.wl = int(new_w)
                self.render()
            return
        if not self._drag:
            return
        x0, y0, wx, wy = self._drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if abs(dx) > 3 or abs(dy) > 3:
            self._moved = True
        self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def on_release(self, e):
        act, self._pending = self._pending, None
        self._drag = None
        self._resize = None
        if act == "close":
            self.quit()
        elif act == "min":
            self.collapsed = True
            self.render()
        elif act == "expand":
            self.collapsed = False
            self.render()
        elif act == "dbl":
            webbrowser.open(self.url + "/")
        elif act is None and not self._moved and self.collapsed:
            # 折叠条上单击（没拖动）→ 展开
            self.collapsed = False
            self.render()

    def on_motion(self, e):
        if self.collapsed:
            self.canvas.configure(cursor="hand2" if e.x < self.W - self.X(30) else "")
        elif e.x >= self.W - self.X(GRIP) and e.y >= self.h_px - self.X(GRIP):
            self.canvas.configure(cursor="size_nw_se")
        else:
            self.canvas.configure(cursor="")

    def toggle_collapse(self):
        if self.collapsed:
            self.collapsed = False
        else:
            self.collapsed = True
        self.render()

    def on_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def restore_pos(self):
        x = y = None
        if os.path.isfile(STATE_FILE):
            try:
                d = json.load(open(STATE_FILE, encoding="utf-8-sig"))
                x, y = d.get("x"), d.get("y")
                self.collapsed = bool(d.get("collapsed", False))
                self.wl = int(d.get("w", W_DEFAULT))
                self.wl = max(W_MIN, min(W_MAX, self.wl))
            except Exception:
                pass
        if not isinstance(x, int):
            x = self.root.winfo_screenwidth() - self.W - self.X(40)
        if not isinstance(y, int):
            y = self.X(60)
        self.root.geometry(f"{self.W}x{self.X(120)}+{x}+{y}")

    def save_pos(self):
        try:
            json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                       "collapsed": self.collapsed, "w": self.wl},
                      open(STATE_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    def quit(self):
        self.save_pos()
        self.stop.set()
        self.root.destroy()

    # ------------------------------------------------------------------ 渲染
    def render(self):
        nodes = (self.data or {}).get("nodes", [])
        self._hit = []
        if self.collapsed:
            self.draw_collapsed(nodes)
        else:
            self.draw_full(nodes)

    def draw_window_buttons(self, c, y, h, collapsed):
        """右上角：最小化/展开 + 关闭。返回两个热区。"""
        x2 = self.W - self.X(8)
        bw, bh = self.X(20), min(self.X(16), h - self.X(8))
        by = y + (h - bh) // 2
        close = (x2 - bw, by, x2, by + bh)
        mini = (close[0] - bw - self.X(2), by, close[0] - self.X(2), by + bh)

        cx = (close[0] + close[2]) / 2
        cy = (close[1] + close[3]) / 2
        d = self.X(4)
        c.create_line(cx - d, cy - d, cx + d, cy + d, fill=MUT, width=max(1, self.X(1.2)))
        c.create_line(cx - d, cy + d, cx + d, cy - d, fill=MUT, width=max(1, self.X(1.2)))

        mx = (mini[0] + mini[2]) / 2
        if collapsed:
            s = self.X(3.5)
            c.create_rectangle(mx - s, cy - s, mx + s, cy + s, outline=MUT,
                               width=max(1, self.X(1.2)))
        else:
            c.create_line(mx - self.X(4), cy + self.X(2), mx + self.X(4), cy + self.X(2),
                          fill=MUT, width=max(1, self.X(1.2)))
        self._hit.append((close[0], close[1], close[2], close[3], "close"))
        self._hit.append((mini[0], mini[1], mini[2], mini[3], "min" if not collapsed else "expand"))

    def draw_collapsed(self, nodes):
        c = self.canvas
        c.delete("all")
        h = self.X(COLLAPSED_H)
        pad = self.X(PAD)
        lw = max(1, self.X(1.1))
        icon_s = self.X(13)
        cy = h / 2
        x = pad + self.X(2)
        limit = self.W - self.X(58)      # 给右上角两个按钮留位置

        def item(kind, pct, dim, charging):
            nonlocal x
            if x > limit:
                return
            color = DIM if dim else TXT
            x += draw_icon(c, kind, x, cy, icon_s, color, lw) + self.X(2)
            t = c.create_text(x, cy, anchor="w", text="—" if pct is None else str(pct),
                              fill=color, font=self.FN(10, bold=True))
            bb = c.bbox(t)
            x = bb[2] + self.X(2)
            if charging and not dim:
                bolt(c, x + self.X(0), cy - self.X(5.5), self.s * 0.75)
                x += self.X(7)
            x += self.X(8)

        first_group = True
        for n in nodes:
            b = n.get("battery") or {}
            off = not n.get("online")
            if not first_group and x <= limit:
                c.create_line(x - self.X(4), cy - self.X(7), x - self.X(4), cy + self.X(7),
                              fill="#4d5f7d", width=max(1, self.X(1)))
                x += self.X(4)
            first_group = False
            item(icon_kind(n.get("name"), n.get("node")), b.get("pct"), off, bool(b.get("ac")))
            for p in n.get("peripherals") or []:
                item(icon_kind(p.get("name"), p.get("id"), p.get("cls", -1)), p.get("pct"),
                     not p.get("connected", True), False)

        self.draw_window_buttons(c, 0, h, True)
        self.h_px = int(h)
        self.root.geometry(f"{self.W}x{self.h_px}")
        self.canvas.configure(width=self.W, height=self.h_px)

    def draw_full(self, nodes):
        c = self.canvas
        c.delete("all")
        stale = self.error is not None
        pad = self.X(PAD)
        y = 0

        # 标题栏
        th = self.X(TITLE_H)
        c.create_text(pad + self.X(2), th / 2, anchor="w", text="电量中枢",
                      fill=DIM if stale else TXT, font=self.F(11, bold=True))
        self.draw_window_buttons(c, 0, th, False)
        y = th

        if not nodes:
            c.create_text(self.W / 2, y + self.X(22), text="还没有节点上报",
                          fill=MUT, font=self.F(11))
            y += self.X(50)

        for n in nodes:
            y = self.draw_card(c, n, y)

        # 底部状态行 + 右下角调宽手柄
        y += self.X(2)
        right = ("离线 · " + (self.error or "")[:22]) if stale else \
                ("更新于 " + ago(int(time.time() - self.last_ok)) if self.last_ok else "连接中")
        c.create_text(pad + self.X(2), y + self.X(6), anchor="nw", text=right,
                      fill=LOW_A if stale else DIM, font=self.F(8))
        y += self.X(20)

        gx, gy = self.W - self.X(6), y - self.X(4)
        for i in range(3):
            o = self.X(3) * i
            c.create_line(gx - self.X(9) + o, gy, gx, gy - self.X(9) + o,
                          fill="#2b3648", width=max(1, self.X(1)))

        self.h_px = int(y)
        self.root.geometry(f"{self.W}x{self.h_px}")
        self.canvas.configure(width=self.W, height=self.h_px)

    def draw_card(self, c, n, y):
        per = n.get("peripherals") or []
        off = not n.get("online")
        pad, gap = self.X(PAD), self.X(GAP)
        h = self.X(74 + 14 * len(per))
        x1, x2 = pad, self.W - pad
        round_rect(c, x1, y, x2, y + h, self.X(11),
                   fill=CARD_OFF if off else CARD, outline=BORDER)

        b = n.get("battery") or {}
        pct, chg, ac = b.get("pct"), b.get("charging"), b.get("ac")

        # 设备类型图标（在线亮、离线灰）
        draw_icon(c, icon_kind(n.get("name"), n.get("node")),
                  x1 + self.X(10), y + self.X(13), self.X(13),
                  DIM if off else TXT, max(1, self.X(1.1)))
        c.create_text(x1 + self.X(29), y + self.X(13), anchor="w",
                      text=n.get("name", n.get("node")),
                      fill=DIM if off else TXT, font=self.F(11))
        state = "离线" if off else ("充电中" if chg else ("已充满" if ac else "放电中"))
        c.create_text(x2 - self.X(11), y + self.X(13), anchor="e", text=state,
                      fill=(AMBER if ac else MUT) if not off else DIM, font=self.F(9))

        num = "—" if pct is None else str(pct)
        item = c.create_text(x1 + self.X(11), y + self.X(19), anchor="nw", text=num,
                             fill=DIM if off else TXT, font=self.FN(25, bold=True))
        if pct is not None:
            bb = c.bbox(item)
            c.create_text(bb[2] + self.X(2), y + self.X(36), anchor="w", text="%",
                          fill=MUT, font=self.FN(11))
            if ac and not off:
                bolt(c, bb[2] + self.X(15), y + self.X(24), self.s * 0.9)

        bx1, bx2 = x1 + self.X(11), x2 - self.X(11)
        by = y + self.X(51)
        round_rect(c, bx1, by, bx2, by + self.X(5), self.X(2.5), fill="#1f2937", outline="")
        if pct:
            w = (bx2 - bx1) * max(0, min(100, pct)) / 100.0
            if w >= self.X(6):
                round_rect(c, bx1, by, bx1 + w, by + self.X(5), self.X(2.5),
                           fill=LOW_A if pct <= 20 else ACC_A, outline="")

        py = y + self.X(61)
        for p in per:
            pp = p.get("pct")
            conn = p.get("connected", True)
            icol = PER if conn else PER_OFF
            draw_icon(c, icon_kind(p.get("name"), p.get("id"), p.get("cls", -1)),
                      bx1, py + self.X(6), self.X(10.5), icol, max(1, self.X(1)))
            c.create_text(bx1 + self.X(15), py, anchor="nw",
                          text=("· " if not conn else "") + p.get("name", "?"),
                          fill=icol, font=self.F(10))
            c.create_text(bx2, py, anchor="ne",
                          text="—" if pp is None else f"{pp}%",
                          fill=PER_VAL if conn else PER_OFF,
                          font=self.FN(10, bold=True))
            py += self.X(14)
        return y + h + gap

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.stop.set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18080")
    ap.add_argument("--interval", type=int, default=5)
    a = ap.parse_args()
    enable_dpi()
    Widget(a.url, a.interval).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
