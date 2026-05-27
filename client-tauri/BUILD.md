# 客户端构建说明（Tauri v2）

## 一次性环境准备

1. **Rust toolchain**（已自动通过 winget 装好 v1.95+）
   ```powershell
   winget install --id Rustlang.Rustup -e
   rustup default stable
   ```

2. **MSVC Build Tools**（链接器必备 —— 仅装 Rust 不够）
   ```powershell
   winget install --id Microsoft.VisualStudio.2022.BuildTools -e
   ```
   勾选「Desktop development with C++」 + 「Windows 11 SDK」。
   或者完整 IDE：`winget install Microsoft.VisualStudio.2022.Community`。

3. **WebView2 Runtime**（Win11 自带；Win10 需手动）
   ```powershell
   Get-AppxPackage Microsoft.Web.WebView2Runtime
   ```
   若缺失：装 https://developer.microsoft.com/microsoft-edge/webview2/

4. **避免中文路径**
   Cargo + MSVC `link.exe` 在中文路径下会出 UTF-8 解析错误。
   把仓库 clone 到 ASCII 路径（如 `C:\dev\yqgl\`）后再 build。

## 开发：跑 dev

```powershell
cd <repo>
npm install                       # 安装 workspaces 依赖
cd client-tauri
npm run tauri:dev                 # 启动 Vite + Tauri，开发热重载
```

第一次会下载 ~30 项 Cargo 依赖并编译（5-15 分钟，取决于网速）。

## 发布：bundle msi/nsis

```powershell
cd client-tauri
npm run tauri:build
# 产物：src-tauri/target/release/bundle/{msi,nsis}/需求管理大师_0.2.0_x64_zh-CN.{msi,exe}
```

安装到 `%LOCALAPPDATA%\Programs\yqgl\`。配置文件 `%APPDATA%\yqgl\config.json`
与老 Python 客户端字段名兼容，无缝迁移。

## 故障排查

| 症状 | 解决 |
|---|---|
| `linker 'link.exe' not found` | 装 VS Build Tools 步骤 2 |
| `link: extra operand …` (字符乱码) | 中文路径 — 移到 ASCII 路径 |
| Mica 未生效 | Win10 没有 Mica，自动回退 Acrylic |
| Tray 不显示 | 任务栏「通知区域」需要打开图标显示 |
| `failed to connect to 192.168.0.224` | Onboarding 重填 IP，或改 `%APPDATA%\yqgl\config.json` |

## 与旧 pywebview 客户端共存

Tauri 客户端读写同一份 `%APPDATA%\yqgl\config.json`，字段同名兼容。
首次启动 Tauri 会复用老配置，无需重新登录或注册设备。
