# 电量中枢 / battery-hub

把 **手机、平板、笔记本、蓝牙耳机、蓝牙键鼠** 的电量和充电状态聚到一处，
在 **Windows 桌面悬浮窗**、**Android 桌面小组件**、**网页面板** 上同时看到。

> 用途：桌面上随手一眼就知道哪台设备该充电了。全部跑在局域网内，不依赖任何云服务。

![PC 悬浮窗](docs/pc-widget.png)

| 折叠成一条 | 手机小组件 |
|---|---|
| ![折叠](docs/pc-widget-collapsed.png) | ![手机](docs/android-widget.png) |

---

## 功能与规则

这一节写的是**实际行为**，不是设想。

### 1. 采集

| 端 | 采集内容 | 方式 |
|---|---|---|
| 手机 / 平板 | 自身电量、充电 | `BatteryManager` 粘性广播 |
| 手机 / 平板 | 每台已配对蓝牙耳机的电量 | 反射 `BluetoothDevice.getBatteryLevel()`（隐藏 API） |
| 手机 / 平板 | 每台外设是否连接 | 反射 `BluetoothDevice.isConnected()` |
| PC | 自身电量、充电、是否插电 | `GetSystemPowerStatus` |

扫描频率：**15 秒一次**，扫的是系统"已配对设备"列表（`getBondedDevices()`），不是扫描周围信号。

> 为什么不用 `BATTERY_LEVEL_CHANGED` 广播？实测在这台机器上一次都不触发。
> 为什么不用 `dumpsys bluetooth_manager`？vivo 把这部分 dump 掏空了，输出 0 字节。

### 2. 上报：事件驱动 + 心跳

| 触发条件 | 是否立即上报 |
|---|---|
| 电量与上次相比变化 ≥ 1% | ✅ 立即 |
| 充电 / 插电状态翻转 | ✅ 立即 |
| 外设连接状态变化 | ✅ 立即 |
| 以上都没有 | 每 **10 分钟**发一次心跳 |

中枢超过 **30 分钟**没收到某节点上报，就把它标记为**离线**（并变灰）。
状态写进 `state.json`，中枢重启后恢复，全部先标记离线、等它们重新上报。

### 3. 外设显示规则

**显示条件**（三条缺一不可）：

1. 在系统"已配对"列表里；
2. **并且**满足下列之一：有过至少一次电量读数 / 当前正在连接。

> 换句话说：从来没读到过电量、现在也没连着的设备**不显示**（避免面板上挂一堆 `—`）。
> 但"连着却读不到电量"的设备**会显示**，只是电量为 `—` —— 因为连着这件事本身是有效信息（比如某些 BLE 鼠标不开放电量服务）。

**显示内容**：

- 有历史电量 → 显示**最后一次读到的电量**，断开后也保留；
- 从未读到过 → 显示 `—`；
- 断开的外设 → 整行**变灰**，名字前加 `·`。

**归属规则（会切换）**：

- 谁**最后**把它报成"已连接"，它就挂在谁下面；
- **防抖**：新设备必须**连续两次**上报"已连接"（约 30 秒）才真正搬过去。
  耳机从平板上断开后常常会"闪一下"回连手机，这条规则就是为了不让归属跟着乱跳；
- 同一只耳机从手机连到平板 → 归属自动从手机搬到平板，不需要手动设置；
- 设备报"已断开"时，只更新它自己名下的那条，**不会**去抢别的设备的外设；
- 外设所属的设备离线时，该外设跟着一起变灰。

### 4. 数值语义：`null` 不等于 `0`

| 字段 | 取值 | 含义 |
|---|---|---|
| `pct` | `0..100` | 正常 |
| `pct` | `null` | **读不到**（不是没电） |
| `charging` | `true` | 正在充电 |
| `charging=false, ac=true` | | 插着电但已充满 |
| `charging=false, ac=false` | | 电池放电中 |

界面上 `null` 一律显示 `—`，绝不显示 `0%`。

### 5. 类型识别（折叠条图标）

三层兜底，命中即止：

| 顺序 | 依据 | 例子 |
|---|---|---|
| 1 | 蓝牙设备类 `getDeviceClass()` | `0x0540`→键盘、`0x0580`→鼠标、`0x04xx`→音频 |
| 2 | 名字关键词 | `耳机/buds/tws/anc/w820/头戴/keyboard/mouse/鼠标/平板/pad…` |
| 3 | 型号前缀 | `K###`→键盘、`M###`→鼠标（联想等厂家惯例） |
| 4 | 兜底 | 通用圆环 |

音频类还会再按名字区分**头戴**（大弧+耳罩）和**豆式**（两颗小豆），因为蓝牙类分不出来。

### 6. 节点识别

- 节点 id 由机型自动生成（`Build.MODEL`），所以**同一个 APK** 装到手机和平板不会互相覆盖；
- 想改名不用重装：`config.json` 里
  - `"aliases": {"opd2513": "平板"}` —— 改**设备**名
  - `"periph_aliases": {"6c1629715c35": "蓝牙耳机"}` —— 改**外设**名（键是 MAC 去掉冒号）

### 7. 网络

- 中枢**同时监听 IPv4 和 IPv6**（同一端口）；
- App 内置**多地址回退**：按 `hub_urls.txt` 的顺序依次尝试，第一个能通的就用
  （典型顺序：局域网 IPv4 → IPv6 → `adb reverse` 隧道）；
- `GET /apk` 可以直接下载最新 APK，省得每次插线；
- **没有自动发现**：实测 mDNS / SSDP 在这类校园网里 0 响应，只能手写地址。

### 8. 界面

**PC 悬浮窗**（`ui/pc_widget.py`）

- 无边框、置顶、半透明，**不占任务栏**（`overrideredirect` + `-toolwindow`，Alt+Tab 里也不出现）
- 设备名和外设名前都有**类型图标**（手机/笔记本/平板/头戴/豆式/键盘/鼠标），在线亮、离线灰
- 右上角 `─` 折叠成一条 30px 横条；`✕` 完全退出
- 折叠条只显示**图标 + 电量**，按设备分组，组间有分隔线
- 拖动移动，位置存 `ui/window.json`
- 右下角斜纹拖拽调宽（260–560）
- 中枢挂掉时保留最后一帧，右上角变橙色"离线 · 原因"，不闪白
- 电量 ≤20% 进度条变橙色

**Android 小组件**（`RemoteViews`）

- 固定 3 行（手机 / 平板 / 电脑），每行"**类型图标** + 名字 + 百分比 + 进度条"，下面一行小字列外设
- 圆角引用系统的 `system_app_widget_background_radius`，和系统小组件一致
- 断开的外设整行变灰；离线设备整行变灰 + `·` 前缀
- 点一下打开网页面板
- 跟着服务的 15 秒扫描节奏刷新

**网页面板**（`/`）：5 秒自动刷新，手机上也能直接看。

### 9. 保活（Android）

- 前台服务 + 常驻低优先级通知（`foregroundServiceType="connectedDevice"`）
- `START_STICKY`：被系统杀掉后自动重建
- `BOOT_COMPLETED`：开机自启
- `MY_PACKAGE_REPLACED`：**覆盖安装后自启**（这条很关键，`START_STICKY` 救不了装完被杀）
- 仍需手动开系统白名单：**完整教程见 [docs/keepalive.md](docs/keepalive.md)**
  （分 ROM 路径 / 验证方法 / 症状对照表）

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
