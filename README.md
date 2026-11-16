# 电量中枢 / battery-hub

把 **手机、平板、笔记本、蓝牙耳机、蓝牙键鼠** 的电量和充电状态聚到一处，
在 **Windows 桌面悬浮窗**、**Android 桌面小组件**、**网页面板** 上同时看到。

> 用途：桌面上随手一眼就知道哪台设备该充电了。全部跑在局域网内，不依赖任何云服务。

![PC 悬浮窗](docs/pc-widget.png)

| 折叠成一条 | 手机小组件 |
|---|---|
| ![折叠](docs/pc-widget-collapsed.png) | ![手机](docs/android-widget.png) |

---

## 架构

```
┌─────────────┐   POST /report   ┌──────────────────────────┐
│ 手机 App    │ ───────────────► │  PC: hub.py              │
│ (前台服务)  │                  │  · 采集本机电量          │
└─────────────┘                  │  · 接收各设备上报        │
┌─────────────┐   POST /report   │  · 外设归属仲裁          │
│ 平板 App    │ ───────────────► │  · state.json 持久化     │
└─────────────┘                  │  · HTTP 面板 /state      │
                                 └────────┬─────────────────┘
                                          │ GET /state
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
              PC 悬浮窗            手机/平板小组件          网页面板
             (Python/Tk)          (RemoteViews)
```

没有 MQTT、没有数据库、没有账号体系。一个 Python 进程 + 一个 APK。

---

## 目录

```
battery-hub/
├─ hub/
│  ├─ hub.py            # 中枢：采集/汇总/持久化/HTTP
│  ├─ battery.py        # Windows 电池读数（区分 充电中/已充满/放电中）
│  ├─ dashboard.html    # 网页面板
│  └─ broker.py         # 备选 MQTT broker（默认不用，见"局限"）
├─ ui/
│  └─ pc_widget.py      # PC 桌面悬浮窗
├─ android/probe/       # Android 端（手工 aapt2/d8 构建，不用 Gradle）
│  ├─ AndroidManifest.xml
│  ├─ hub_urls.example.txt   # 中枢地址模板，复制成 hub_urls.txt
│  ├─ res/                   # 布局、小组件描述、圆角背景
│  └─ src/hub/probe/
│     ├─ HubService.java     # 前台服务：扫描蓝牙 + 上报
│     ├─ HubWidget.java      # 桌面小组件
│     ├─ BootReceiver.java   # 开机 / 覆盖安装后自启
│     └─ ProbeActivity.java  # 只有授权 + 拉起服务
├─ tools/
│  ├─ build_probe.ps1   # 手工构建 APK（aapt2 → javac → d8 → 签名）
│  └─ fake_node.py      # 假节点，调界面用
├─ config.example.json
└─ start-hub.cmd
```

---

## 快速开始

### 1. PC 端

```powershell
cd battery-hub
python -m pip install -r requirements.txt
copy config.example.json config.json
python hub/hub.py          # 中枢，监听 18080
python ui/pc_widget.py     # 悬浮窗（可另开窗口）
```

或者直接双击 `start-hub.cmd`。

面板：`http://127.0.0.1:18080/`

### 2. Android 端

需要 JDK 17 + Android SDK（platform-35、build-tools 35）。仓库**不含**这些，因为体积太大。

```powershell
# 1) 写中枢地址（这个文件不进 git）
copy android/probe/hub_urls.example.txt android/probe/hub_urls.txt
notepad android/probe/hub_urls.txt

# 2) 构建
powershell -ExecutionPolicy Bypass -File tools/build_probe.ps1

# 3) 安装
adb install -r -g android/out/probe.apk
adb shell am start -n hub.probe/.ProbeActivity
```

> `-g` 很关键：一次授予全部运行时权限。某些 ROM（如 OxygenOS）不允许 `pm grant`。

装完去桌面长按空白 → 小组件 → **HubProbe**。

### 3. 地址清单

`hub_urls.txt` 里每行一个地址，App 按顺序试，第一个能通的就用：

```
http://192.168.1.100:18080/report          # 局域网 IPv4
http://[fd00::1]:18080/report              # IPv6（IPv4 不通时用）
http://127.0.0.1:18080/report              # adb reverse 兜底
```

---

## 数据格式

### `POST /report`

```json
{
  "node": "iqooz8",
  "name": "iQOO Z8",
  "ts": 1763270000,
  "battery": { "pct": 87, "charging": false, "ac": false },
  "peripherals": [
    { "id": "cc14bcadbc77", "name": "EDIFIER W820NB", "pct": 90, "connected": true, "cls": 1028 },
    { "id": "119f9f6bbf78", "name": "Lenovo K211",  "pct": 85, "connected": true, "cls": -1 }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `pct` | `null` = 读不到（不是没电） |
| `charging` | 正在充电 |
| `ac` | 插着电源（充满时 `charging=false, ac=true`） |
| `connected` | 该外设当前是否连着 |
| `cls` | `BluetoothClass.getDeviceClass()`，用来判断键鼠/耳机；BLE 设备常为 -1 |

### `GET /state`

```json
{ "hub_ts": 1763270000, "count": 3,
  "nodes": [ { "node":"pc", "name":"Win10 笔电", "online":true, "age_sec":3,
               "battery":{...}, "peripherals":[...] } ] }
```

**外设归属规则**：谁最后把它报成 `connected:true`，它就固定挂在那台设备下面。
耳机在手机/平板之间切换时会自动搬家；`connected:false` 时保留最后一次电量并变灰。

---

## 已知局限（请务必先读）

### 网络

1. **IPv6 地址是写死的。** 电脑换网络（换 AP、换热点）后 IPv6 前缀会变，平板就失联。
   IPv4 通的设备不受影响。
2. **校园网/企业网可能不给客户端做代理 ARP。** 实测某校园网中，平板 ARP 电脑的 IPv4
   返回 `INCOMPLETE`，但 IPv6 通。这就是为什么地址清单要支持多条。
3. **8080 这类端口可能被网络封掉。** 本项目用 18080，但换网络后仍可能撞上。
4. **Tailscale 等 VPN 会劫持本地路由。** 平板上开着 Tailscale 时，连网关都是
   `No route to host`。要么关掉，要么给它加局域网直连例外。
5. **组播基本不能指望。** 实测 mDNS、SSDP 在该校园网均 0 响应，所以没做自动发现，
   地址只能手写。

### Windows

6. **防火墙的"程序阻止规则"会压过端口放行规则。** 如果 `python.exe` 曾被误点"取消"，
   会留下 Block 规则，任何端口规则都不生效。排查：
   ```powershell
   netsh advfirewall firewall show rule name=all dir=in | findstr /i python
   ```
   有 Block 就删掉。

### Android

7. **依赖隐藏 API。** 耳机电量靠反射调用 `BluetoothDevice.getBatteryLevel()`
   （不在公开 SDK 里）。某些 ROM 会拦，OTA 后也可能失效。
   实测 iQOO Z8 / Android 15 可用，OnePlus / Android 16 未验证。
8. **`BATTERY_LEVEL_CHANGED` 广播不触发。** 实测全程 0 条，别指望它。
9. **`dumpsys bluetooth_manager` 在部分 ROM 上是空的**（vivo 实测 0 字节），
   所以没法用 adb 验证电量，只能靠 App。
10. **保活要手动配置。** 前台服务只是及格线，OriginOS / OxygenOS 还需要：
    自启动、后台高耗电、电池不受限制、最近任务锁定。
11. **小组件布局固定 3 行。** RemoteViews 不支持动态增删，多于 3 台设备会显示不下。
12. **窄屏/换行**：外设名过长会挤，目前靠一行一个外设缓解。

### 功能

13. **ESP32 屏尚未实现**（见路线图）。
14. **充电状态对耳机不可得**，只能显示"连接/断开"。
15. **没有历史曲线**、没有低电量提醒、没有多用户/认证（`http.token` 预留了但没启用）。

---

## 踩过的坑（复现时会遇到）

| 现象 | 原因 | 处理 |
|---|---|---|
| `POST /report` 全部超时，但本机 curl 正常 | Windows 防火墙有 `python.exe` 的 Block 规则 | 删除该规则 |
| 装完 APK 后数据不再更新 | 覆盖安装会杀掉进程，`START_STICKY` 救不了 | 已内置 `MY_PACKAGE_REPLACED` 自启 |
| `pm grant` 报 `GRANT_RUNTIME_PERMISSIONS` 拒绝 | Android 16 / OxygenOS 限制 | `adb install -g` |
| 改了端口后悬浮窗空白 | 默认 URL 没跟着改 | 检查 `--url` 默认值 |
| 配置文件读不出来 | PowerShell `Set-Content -Encoding UTF8` 写了 BOM | 用无 BOM 写入 |
| 中文源码编译报错 | 同上的编码问题 | 用 UTF-8 无 BOM 保存 |
| Tk 文字重叠/被裁 | Windows 125% 缩放，字体按磅、坐标按像素 | 统一乘 DPI 因子，字号用负值 |

---

## 路线图

- [ ] **ESP32 桌面屏**：ESP32-S3 + 2.4" ST7789 + LD2410C 毫米波人感，
      `人来自动亮屏，人走熄屏`，每 10 分钟拉一次 `/state`
- [ ] 平板端白名单引导页
- [ ] 低电量通知
- [ ] 地址自动发现（局域网有 DHCP 保留或固定 IP 之后）

---

## 许可

MIT。自行取用，出问题自负。
