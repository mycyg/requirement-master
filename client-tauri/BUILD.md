# 客户端构建说明（Tauri v2）

> **真实编译验证状态**（2026-05-28，Windows 11 + ASCII 路径）：
> - ✅ `cargo check` 通过（2 个无害 dead-code warning）
> - ✅ `cargo build` 通过，1m 47s
> - ✅ `cargo tauri build --no-bundle` 通过 → `target\release\yqgl-client.exe` (19 MB)
> - ✅ 启动 exe 成功（进程跑起来、占 25 MB 内存）
> - ⚠️ `tauri build`（含 MSI/NSIS bundle）会失败：
>   - WiX MSI: candle 编译 wxs 出错（中文产品名兼容性）
>   - NSIS: extract 阶段触发 "无法跨盘 rename" — Tauri 已知 bug，与本仓库代码无关
>   - **dev 与发布 exe 都不受影响**。要做 distribution 包请用 GitHub Actions 在
>     Linux runner 上跑 `tauri build`，或本地手动改用 Inno Setup / 直接发布 zip。

## 一次性环境准备

1. **Rust toolchain**
   ```powershell
   winget install --id Rustlang.Rustup -e
   rustup default stable
   ```

2. **MSVC Build Tools**（必备 —— 仅装 Rust 不够）
   ```powershell
   $u = "https://aka.ms/vs/17/release/vs_BuildTools.exe"
   curl -L -o $env:TEMP\vs_bt.exe $u
   & $env:TEMP\vs_bt.exe --quiet --wait --norestart `
       --add Microsoft.VisualStudio.Workload.VCTools `
       --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
       --add Microsoft.VisualStudio.Component.Windows11SDK.22621
   ```
   `winget install Microsoft.VisualStudio.2022.BuildTools` 不带 workload，
   会因为 GUI 弹窗在 silent 模式被取消（exit code 1602）。

3. **WebView2 Runtime**（Win11 自带）—— `Get-AppxPackage Microsoft.Web.WebView2Runtime` 检查

4. **避免中文路径**
   Rust + MSVC `link.exe` 在中文路径下会出 UTF-8 解析错误（"link: extra operand"）。
   把仓库 clone 到 ASCII 路径（如 `C:\dev\yqgl\`）后再 build。

## 开发：跑 dev

```powershell
cd <repo-on-ASCII-path>
npm install                       # 安装 workspaces 依赖
cd client-tauri
npm run tauri:dev                 # vite + cargo run + 热重载
```

第一次会下载 ~200 Cargo deps 并编译（5-15 分钟）。

## 发布

```powershell
cd client-tauri
npx tauri build --no-bundle       # 出 target\release\yqgl-client.exe (~19MB)
```

实测 `--no-bundle` 工作正常。带 bundle 的 MSI/NSIS 在本机会卡 WiX/NSIS
跨盘 rename，需在 Linux runner 或换 Inno Setup（见上）。

## 故障排查

| 症状 | 解决 |
|---|---|
| `linker 'link.exe' not found` | 装 VS Build Tools 步骤 2 |
| `link: extra operand …` (字符乱码) | 中文路径 — 移到 ASCII 路径 |
| `unknown variant 'perUser'` | Tauri v2 用 `currentUser` 不是 `perUser`（已修） |
| `os error 17 ... 无法将文件移到不同的磁盘驱动器` | NSIS bundle 跨卷 rename bug，跳过 bundle 或换 Inno Setup |
| Mica 未生效 | Win10 没有 Mica，自动回退 Acrylic |
| Tray 不显示 | 任务栏「通知区域」需要打开图标显示 |
| `failed to connect to 192.168.0.224` | Onboarding 重填 IP，或改 `%APPDATA%\yqgl\config.json` |

## 与旧 pywebview 客户端共存

Tauri 客户端读写同一份 `%APPDATA%\yqgl\config.json`，字段同名兼容。
首次启动 Tauri 会复用老配置，无需重新登录或注册设备。
默认 IP `192.168.0.224`，会自动把老配置里 `192.168.5.x` 改写到 `192.168.0.x`
（针对旧 pywebview 客户端默认 IP 写错的兼容）。
