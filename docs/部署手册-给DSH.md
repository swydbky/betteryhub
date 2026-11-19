# battery-hub · 部署手册（给 DSH 执行）

> 读者：AI 助手。读完这份就能自己装完、配好、验完。
> 只列 **必须由人类动手** 的 3 件事，其余全部由你执行。
> 面向人类的完整图文版在 [`使用指南.md`](使用指南.md)，不要拿它当执行清单。

---

## 0. 一句话

Windows 电脑跑一个 HTTP 中枢（`:18080`），安卓手机/平板把电量 POST 过去；
跨网络靠 **OpenFrp TCP 隧道**（因为校园网隔离客户端，局域网直连不可用）。

---

## 1. 先自检（30 秒，决定要不要重装）

| # | 命令 | 通过标准 |
|---|---|---|
| 1 | `Get-Process frpc` | 有进程 |
| 2 | `curl.exe http://127.0.0.1:18080/health` | `{"ok": true, ...}` |
| 3 | `curl.exe http://<隧道域名>:<远程端口>/state` | 返回 JSON，`count >= 1` |
| 4 | 同上，看 `nodes[].online` | 目标设备 `true` |

**4 条全过 = 已部署完成**，直接跳第 5 节验收。
只缺某一条 → 看第 4 节排障表，不要整机重装。

---

## 2. 人类必须做的（只有 3 件）

| # | 事项 | 为什么 AI 做不了 | 产出物（交给你） |
|---|---|---|---|
| **H1** | 注册 OpenFrp、建隧道、复制配置 | 要邮箱验证码、可能实名；账号归人所有 | 一段 `frpc` 配置文本 |
| **H2** | 手机/平板装 APK、填地址、授权 | 点"允许未知来源"、蓝牙/通知授权必须手点 | 设备开始上报 |
| **H3** | 添加桌面小组件 | 桌面长按拖拽只能手动 | 桌面可见（可选） |

> 如果机器能连 adb（USB 或无线调试），H2 可降级为 `adb install -r -g android\out\probe.apk`，
> 但仍需人工点一次授权弹窗。

### H1 · 拿隧道配置（约 5 分钟）

让人打开 [openfrp.net](https://www.openfrp.net)，按顺序：

1. 注册（邮箱 + 密码 + 图形验证码）→ 邮箱点验证链接 → 登录
2. 左边 **隧道** → **创建隧道**，按下表填：

   | 字段 | 值 |
   |---|---|
   | 类型 | **TCP**（不要 HTTP/HTTPS，那两个要备案） |
   | 本地地址 | `127.0.0.1` |
   | 本地端口 | `18080` |
   | 节点 | **海外**节点（免实名）；大陆节点需实名 |
   | 远程端口 | 留空，系统自动分配 |

3. 进隧道详情 → **「配置文件」** → 整段复制 → 发给你

配置长这样（字段名可能略有差异）：

```toml
serverAddr = 'cn-hk-bgp-4.ofalias.net'
serverPort = 8120
user = '<32位 hex>'
[auth]
method = 'token'
token = '<16位>'
[[proxies]]
localIP = '127.0.0.1'
localPort = 18080
name = 'NlMn6ym'
remotePort = 33724
type = 'tcp'
[transport]
protocol = 'tcp'
[transport.tls]
enable = true
serverName = 'n29d19.openfrp.net'
disableCustomTLSFirstByte = false
```

⚠️ **`serverName` 只是 TLS 证书名，DNS 解析不出来，不能当访问域名。**
访问域名 = `serverAddr`，访问地址 = `http://{serverAddr}:{remotePort}`。

### H2 · 手机上装 App（约 3 分钟）

1. 手机浏览器打开 `http://{serverAddr}:{remotePort}/apk`
2. **不要**在浏览器里直接点开；去「文件管理 → 下载」点 `probe.apk` 安装
3. 提示未知来源 → 给浏览器/文件管理授权 → 返回重装
4. 打开 App，确认地址框第一条是 `http://{serverAddr}:{remotePort}/report` → 点 **保存并重启上报**
5. 权限全允许（蓝牙、通知）

平板同样操作；**同一个 APK**，按机型自动区分节点。

### H3 · 桌面小组件（可选，30 秒）

长按桌面空白 → 小组件 → 选 `电量中枢 2×2 / 4×2 / 4×4` → 拖到桌面。
装新 APK 后**旧组件必须删掉重加**，否则还是老布局。

---

## 3. 你自己做的（无需人类）

| # | 动作 | 命令 / 位置 | 成功判据 |
|---|---|---|---|
| D1 | 装依赖 | `pip install -r requirements.txt` | 退出码 0 |
| D2 | 放行端口 | `New-NetFirewallRule -DisplayName "battery-hub-18080" -Direction Inbound -Protocol TCP -LocalPort 18080 -Action Allow -Profile Any` | `netsh advfirewall firewall show rule name="battery-hub-18080"` 有 Allow |
| D3 | 写隧道配置 | 把 H1 的文本存成 `tools\frp\frpc.toml` | `frpc.exe verify -c tools\frp\frpc.toml` 输出 `syntax is ok` |
| D4 | 起服务 | 双击 `start-hub.cmd`（含 hub + 隧道 + 悬浮窗） | `log\frpc.log` 出现 `start proxy success`；`/health` 返回 ok |
| D5 | 开机自启 | `shell:startup` 里放 `start-hub.cmd` 的快捷方式 | 快捷方式存在 |
| D6 | 构建 APK | `powershell -ExecutionPolicy Bypass -File tools\build_probe.ps1` | 输出 `APK: ...\android\out\probe.apk (xx KB)` |
| D7 | 验收 | 见第 5 节 | 全绿 |

**配置要点**：

- 中枢默认 `0.0.0.0:18080` + `[::]:18080` 双栈；**8080 被校园网封**，不要改
- APK 的默认地址清单在 `android\probe\hub_urls.txt`（构建时注入 `res/values/strings.xml`）
- App 内可手改地址（SharedPreferences `hubprobe` / 键 `urls`），**改地址不必重打包**
- `tools/frp/` 已在 `.gitignore`（含 token），**不要提交**

---

## 4. 排障判定表（给你自己看）

| 现象 | 判定 | 动作 |
|---|---|---|
| `/health` 不通 | hub 没跑 | 起 hub，看 `log\hub.err` |
| 公网 `/health` 不通、本机正常 | 隧道没跑 / 配置错 | 起 frpc，看 `log\frpc.log` |
| frpc 日志 `connect timeout` | 节点被封或挂了 | 让人类换节点重建隧道，更新 `frpc.toml` |
| frpc 日志 `proxy already exists` | 上次没退干净 | 等 30s 重启 |
| 手机能上网但打不开面板 | 地址写成 `serverName` 了 | 换成 `serverAddr:remotePort` |
| 设备 online 但数据旧 | 心跳 10 分钟一次，正常 | 等下一轮 |
| 设备 30 分钟没上报 | 被判离线 | 查手机保活白名单 |
| 平板装不上 APK | 下载没落成 `.apk` / 未知来源没开 | 让人类用文件管理器打开；`/apk` 已带 `Content-Disposition: attachment` |
| 装完小组件没变化 | 系统沿用了旧 RemoteViews | 删掉重加 |

---

## 5. 验收（一条命令看全）

```powershell
curl.exe http://{serverAddr}:{remotePort}/state
```

通过标准：

```json
{"hub_ts":<近 60s 内>, "count":N,
 "nodes":[{"node":"pc","online":true,"age_sec":<小>,"battery":{"pct":..}, "peripherals":[...]} ...]}
```

- `hub_ts` 在 60 秒内
- 目标设备 `online: true` 且 `age_sec` 小于 600
- 外设 `peripherals[]` 里有耳机的 `pct`

---

## 6. 常量表

| 项 | 值 |
|---|---|
| 中枢端口 | `18080`（8080 被校园网封） |
| 本机面板 | `http://127.0.0.1:18080` |
| 状态接口 | `/state` · 健康检查 `/health` · 下载 APK `/apk` |
| frpc | `tools\frp\frp_0.72.0_windows_amd64\frpc.exe`（v0.72，TOML 配置） |
| 隧道配置 | `tools\frp\frpc.toml` |
| 日志 | `log\hub.out` · `log\hub.err` · `log\frpc.log` |
| 启动脚本 | `start-hub.cmd`（含隧道）· `tools\start-tunnel.cmd`（只起隧道） |
| APK 产物 | `android\out\probe.apk` |
| 上报规则 | 变化 ≥1% / 充电翻转 / 外设连断 → 立即；否则 10 分钟心跳；30 分钟判离线 |
| 免费额度 | OpenFrp 2 隧道 / 1GB 月流量 / 12Mbps |
