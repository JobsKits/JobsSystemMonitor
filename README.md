# `JobsSystemMonitor`

![Jobs出品，必属精品](https://picsum.photos/1500/400)

<!-- jobs-toc:start -->
<!-- jobs-toc:source {"v":2,"token":"[toc]"} -->
<details>
<summary>📚 目录（点击展开 / 收起）</summary>

- [🔥 前言](#jobs-toc-heading-1)
- [一、功能与边界](#features)
- [二、运行成品](#run)
  - [2.1、Mac](#jobs-toc-heading-4)
  - [2.2、Windows](#jobs-toc-heading-5)
- [三、双端打包](#build)
  - [【MacOS】📦生成dmg.command](#jobs-toc-heading-7)
  - [【Windows】📦生成exe.bat](#jobs-toc-heading-8)
- [四、指标口径](#metrics)
- [五、源码与验证](#development)
- [六、日志与排查](#troubleshooting)
- [七、本仓目录与脚本入口](#repository-layout-and-entrypoints)

</details>
<!-- jobs-toc:end -->

---

## <span id="jobs-toc-heading-1" data-jobs-toc="v2">🔥 <font id=前言>前言</font></span><!-- jobs-toc:heading-end -->

使用 [**Python**](https://www.python.org) 编写的整机监控工具：在 [**macOS**](https://www.apple.com/macos/) 菜单栏显示 CPU / GPU / 内存占用和上下行速率，在 [**Windows**](https://www.microsoft.com/windows) 任务栏区域显示可拖动监控条，并提供托盘入口。参考用户提供的紧凑监控样式，专注实时监控。

导航：[功能与边界](#features) · [运行成品](#run) · [双端打包](#build) · [指标口径](#metrics) · [源码与验证](#development) · [日志与排查](#troubleshooting)。

## 一、<span id="features">功能与边界</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

| 功能 | 行为 |
| --- | --- |
| Mac 菜单栏 | 原生可变宽度 `NSStatusItem`，两行显示百分比及 CPU / GPU / MEM 标签、上传 / 下载；点击打开详情。 |
| Windows 任务栏 | 置顶浮层定位到主任务栏通知区左侧；支持拖动、保存位置、右键菜单和重置位置。 |
| 详情面板 | CPU / GPU / 内存卡片、上下行速率、最近 60 个采样点趋势、硬件与网卡信息。 |
| 网卡 | 默认合计活跃物理网卡；可手动选择特定网卡，包括 VPN / 虚拟网卡；提供刷新入口。 |
| 刷新 | 可选 0.5 / 1 / 2 / 5 秒，默认 1 秒；Mac GPU 成功采集最多每 2 秒一次。 |
| 主题 | 白天 / 黑夜 / 跟随系统，默认跟随系统；设置与位置重启恢复，系统模式监听外观变化。 |
| 输入焦点 | 后台刷新只更新数据与位置，不反复显示、提升或激活窗口；只有点击详情入口才激活面板。 |
| 异常 | 未预热、掉线或不支持时显示 `--`，采集失败可重新采集；未知值不绘制为 0%。 |

Windows 监控条是独立浮层，**不会为任务栏原生按钮自动预留空间**。若遮住图标，可拖动到空处；任务栏空间不足、竖向任务栏放不下或 Explorer 暂不可用时回退桌面浮窗。自动隐藏任务栏和全屏应用时尝试隐藏监控条；原生 Windows 桌面行为仍需目标机验收。

Mac 菜单栏由系统自动匹配文字颜色；详情与桌面悬浮条使用用户选择的主题。刘海屏或菜单栏图标较多时，系统可能隐藏过宽的菜单栏项；可先关闭部分其它菜单栏图标，再开启本工具的桌面悬浮条。

本工具只读本机系统指标，不上传数据、不抓取数据包内容、不清理内存、不结束进程、不自动设置开机启动。无需管理员权限，也没有常驻后端服务。首次启动显示详情，之后可点击菜单栏 / 托盘 / 监控条打开；关闭详情窗口仅收起，点击“退出”才结束进程。

## 二、<span id="run">运行成品</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

### <span id="jobs-toc-heading-4" data-jobs-toc="v2">2.1、Mac <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a></span><!-- jobs-toc:heading-end -->

成功构建后，第一层 `./JobsSystemMonitor.app` 和 `./JobsSystemMonitor.dmg` 为指向最新时间目录的相对符号链接。可直接打开 APP；也可打开 DMG，将 APP 拖入“应用程序”。成品包含运行时，不需要另外安装 Python 或依赖。

Mac 安装包按本机构建架构生成；Apple Silicon 构建不代表 Intel 构建已验证。当前安装包使用本地临时签名，未经过开发者签名与公证；公开分发时应补齐正式签名、公证和许可文件。请按系统正常“隐私与安全性”流程处理自己构建的应用，不需要关闭系统安全保护。

### <span id="jobs-toc-heading-5" data-jobs-toc="v2">2.2、Windows <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a></span><!-- jobs-toc:heading-end -->

成功构建后，第一层 `./JobsSystemMonitor.exe.lnk` 启动程序，`./JobsSystemMonitor.zip.lnk` 指向完整分发包。分发时发送 ZIP；接收方解压后运行 `JobsSystemMonitor/JobsSystemMonitor.exe`，**不能只复制 EXE**，同层 `_internal` 保存必要的 Python 与图形库。

若托盘图标被 Windows 折叠，可在托盘展开区域找到本工具；任务栏监控条默认开启。支持的系统版本由所用 [**Qt / PySide6**](https://doc.qt.io/qtforpython-6/) wheel 决定，建议 Windows 10 / 11 的 64 位环境；旧系统不在验收范围。

## 三、<span id="build">双端打包</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

| 第一层脚本 | 运行平台 | 交付内容 |
| --- | --- | --- |
| `./【MacOS】📦生成dmg.command` | macOS 本机 | APP + DMG，校验后打开 Finder 并启动本次 APP。 |
| `./【Windows】📦生成exe.bat` | Windows 本机 | EXE 目录 + ZIP，校验后打开资源管理器并启动本次 EXE。 |

所有 `./` 路径均相对于打包脚本所在的工具交付目录。克隆目录可命名为 `JobsSystemMonitor`、`JobsSystemMonitor.py` 或其它名称；内部 `./JobsSystemMonitor/` 工程目录保持原结构，`dist/`、`work/` 和产物入口始终定位到当前工具交付目录。

1、构建机需要 Python 3.11 或更新版本；Mac 入口使用本脚本内封装的具名自检函数，检查、安装或更新 [**Homebrew**](https://brew.sh/)，再检查其管理的 Python。已有 Homebrew 执行 `brew update` 更新自身与配方索引，不升级无关软件；Python 满足要求就复用，缺失或不兼容才安装 / 升级 `python@3.13` 并复检。自检实现完整随脚本携带，不依赖外部支持库、同步脚本、系统旧 Python、uv 或父仓目录。Windows 仍需预先安装合适的 Python，双端分别本机打包。

2、双击对应入口，先阅读自述并回车确认环境准备，`Ctrl+C` 取消。需要安装 Homebrew 时，精确输入 `YES` 选系统标准目录，其它输入或回车选用户目录；权限由官方安装器处理，失败不切换路线。Python 必需修复直接回车执行，任意非空输入（含空格）、EOF 或没有交互输入均停止。环境就绪后，内层构建器另行确认本次打包和旧包清理；`--help` 仅展示说明。已有低版或损坏 `.venv` 经确认完整改名备份后重建，备份保留。

  Homebrew 下载遇到连接重置、超时或临时服务端错误时，每个地址最多尝试 3 次，每次连接超时 10 秒、总超时 30 秒，重试间隔 1 秒。系统安装器先从官方 `raw.githubusercontent.com/Homebrew/install` 获取，失败时改从 [**GitHub 官方内容 API**](https://docs.github.com/en/rest/repos/contents#get-repository-content) 获取同一仓库的原始脚本；这只切换下载地址，安装目录保持原选择。下载完成后检查非空、Bash 脚本头和语法，再执行一次安装；安装执行失败不重试。用户目录安装的稳定版本查询使用相同的有限下载重试，Git 克隆失败仍立即停止。

3、构建器优先复用入口选中解释器的健康依赖，其次复用内层 `./JobsSystemMonitor/.venv`。缺少必需依赖时，**直接回车安装；输入任何字符（含空格）后回车取消整个流程**。安装使用 [**pip**](https://pip.pypa.io/) 访问包源，仅修复缺失或不兼容项，不主动升级健康环境；安装失败或复检失败会停止。

4、环境检查通过后，删除本工具固定 `./dist/` 中全部旧产物，并移除指向它的旧快捷入口。拒绝符号链接 / 外部输出目录，清理失败立即停止；不清理源码或其它应用。

5、[**PyInstaller**](https://pyinstaller.org/) 将运行时与依赖打入 `./dist/YYYY.MM.DD HH-mm-ss/`，时间取本机本次构建时间。Mac 额外生成并校验 DMG，Windows 校验 EXE 与完整 ZIP，然后更新第一层最新产物入口。

6、成功后先打开本次产物磁盘位置，再启动本次软件，结尾不再要求回车。失败时不启动旧包；Windows 失败时保留终端。更新正在运行的版本前，请先从监控面板“退出”，以便新进程读取新版本。

构建日志为系统临时目录中的 `JobsSystemMonitor-build.log`；实际位置在入口自述中显示。Mac 在确认环境准备后初始化该日志，记录环境诊断、Homebrew 下载地址、尝试次数及原始 curl / HTTP 错误码；内层构建继续记录打包日志。构建中间文件保存在 `./work/<构建时间>/`，已忽略入库；交付时只需分发 APP / DMG 或完整 Windows ZIP。

### <span id="jobs-toc-heading-7" data-jobs-toc="v2">[【MacOS】📦生成dmg.command](./【MacOS】📦生成dmg.command)</span><!-- jobs-toc:heading-end -->

> **目的：** 在本机生成 JobsSystemMonitor 的 APP / DMG，并打开本次成品。

* 阅读自述，确认环境准备；检查 Homebrew 和兼容的 Python，再交给本工程构建器。
  * 必需依赖缺失：回车安装，任意非空输入取消；环境或复检失败时停止。
* 确认构建范围后准备虚拟环境与依赖，仅清理本工具外层 `dist/` 的旧产物。
* 打包并校验 APP，封装 DMG，统一输出到 `dist/YYYY.MM.DD HH-mm-ss/`。
* 更新第一层产物快捷方式，打开产物目录，再启动本次 APP；失败时查看系统临时目录中的构建日志。

### <span id="jobs-toc-heading-8" data-jobs-toc="v2">[【Windows】📦生成exe.bat](./【Windows】📦生成exe.bat)</span><!-- jobs-toc:heading-end -->

> **目的：** 在 Windows 本机生成 JobsSystemMonitor 的 EXE 分发目录与 ZIP。

* 显示构建说明，依次检查 `py -3` 和 `python`，转交本工程构建器。
  * 没有可用 Python 3.11+：提示安装并停止；`--help` 只显示说明。
* 确认后准备项目虚拟环境；必需依赖缺失时回车安装，任意非空输入取消。
* 清理本工具外层 `dist/`，生成并核验 EXE 目录和 ZIP，保存到同一构建时间目录。
* 更新 EXE / ZIP 快捷方式，打开产物目录并启动新 EXE；失败时停止并保留日志。

## 四、<span id="metrics">指标口径</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

| 指标 | 来源与口径 |
| --- | --- |
| CPU | [**psutil**](https://psutil.io/api/) 的系统 CPU 百分比；首次调用只建立基线，下一次才发布占用。 |
| 内存 | `virtual_memory().percent`；详情已用内存按 `total - available` 展示，避免缓存统计口径冲突。不是内存压力。 |
| 网络 | 逐网卡累计字节差分 / 单调时钟间隔。自动模式排除回环、停用、无 IP 和常见虚拟 / 隧道网卡，避免重复统计；多张符合条件网卡取合计。 |
| 单位 | `B/s` 为字节 / 秒，`K/s`、`M/s`、`G/s` 按 1024 进位，分别对应 KiB/s、MiB/s、GiB/s；不是运营商使用的 bit/s。 |
| Mac GPU | 读取 `ioreg` 的 `IOAccelerator / PerformanceStatistics / Device Utilization %`，多个 GPU 取最忙设备；本机 Apple M5 已实测。 |
| Windows GPU | 原生 PDH `GPU Engine(*) / Utilization Percentage`；同一引擎逐进程合计，再取最忙引擎 / 设备。需要兼容的 WDDM 驱动，不要求 NVIDIA。 |

自动网卡过滤使用名称和地址启发式规则；特殊命名的虚拟网卡可能未被识别，桥接、虚拟交换机或全隧道 VPN 环境建议手动指定实际出口网卡。掉线、切换或字节计数器复位时重新建立基线；速率暂显示 `--`。切换网卡后清空网络历史，避免把两张网卡的曲线连起来。

Mac 驱动字段没有跨硬件 / 系统版本稳定保证；Windows GPU 计数器也可能因驱动、远程桌面或未预热而缺失。读不到时显示原因，失败 60 秒后重试，也可点击“重新采集”。不通过请求管理员权限或执行 `powermetrics` 强行补值。驱动报告的零使用率会正常显示 `0%`。

参考：[Apple IORegistry](https://developer.apple.com/library/archive/documentation/DeviceDrivers/Conceptual/IOKitFundamentals/TheRegistry/TheRegistry.html)、[PDH 英文计数器](https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhaddenglishcounterw)、[PDH 数组读取](https://learn.microsoft.com/en-us/windows/win32/api/pdh/nf-pdh-pdhgetformattedcounterarrayw)、[任务管理器 GPU 最忙引擎口径](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/)。

## 五、<span id="development">源码与验证</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

```text
工具交付目录/                      # 克隆目录名称可自定
├── README.md
├── 【MacOS】📦生成dmg.command
├── 【Windows】📦生成exe.bat
├── dist/YYYY.MM.DD HH-mm-ss/       # 本机生成物
├── work/                          # 本机构建中间文件
└── JobsSystemMonitor/
    ├── pyproject.toml
    ├── assets/icon.png
    ├── scripts/                   # 构建器、启动入口与快捷方式
    ├── src/jobs_system_monitor/
    │   ├── app.py                 # 生命周期、线程、设置
    │   ├── metrics.py             # CPU、GPU、内存与网络采集
    │   ├── macos_status.py        # 原生菜单栏，无额外桥接依赖
    │   ├── windows_bar.py         # 任务栏定位与隐藏检测
    │   ├── appearance.py          # 三态主题
    │   └── ui.py                  # 监控条与详情
    └── tests/
```

在已安装运行依赖的开发环境中，从本文目录执行以下命令，无须安装本项目包：

```shell
python3 ./JobsSystemMonitor/scripts/launch.py --window
python3 ./JobsSystemMonitor/scripts/launch.py --diagnose
```

`--diagnose` 预热约 1 秒后输出一次真实采样 JSON 并退出。Windows 命令可将 `python3` 替换为 `py -3`。依赖版本见 `./JobsSystemMonitor/pyproject.toml`。

测试命令（macOS，已安装依赖的解释器）：

```shell
cd ./JobsSystemMonitor
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts tests
zsh -n ../【MacOS】📦生成dmg.command
```

已验证：macOS Apple Silicon 真实 CPU / GPU / 内存 / 网络采样、原生菜单栏绘制与点击、主题界面渲染、设置重启恢复、采集与构建安全测试、APP / DMG 实际构建和成品启动。

Windows 已完成任务栏几何、DPI、PDH 采集与依赖资源关闭的模拟测试，以及 BAT 路径 / 变量静态检查；**尚未在 Windows 真实机器构建或验收**。外部系统主题变化的即时跟随仍需在两端目标桌面进一步验收；应用主题切换和配置恢复已测试。Intel Mac、其它 GPU、不同缩放、多屏与任务栏自动隐藏属于目标机验证范围。

图标复用本工具集合仓库现有 `icon.png`，打包到 `./JobsSystemMonitor/assets/icon.png`；未新增外部下载素材。菜单栏为程序绘制的文字，运行时没有远程图片依赖。源码只使用 Python 与系统 API，不包含第三方源码副本。

## 六、<span id="troubleshooting">日志与排查</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

运行日志 `monitor.log` 保存在 Qt 当前用户应用数据目录中：Mac 通常为用户资源库下 `Application Support/Jobs/JobsSystemMonitor`，Windows 通常为本地应用数据下 `Jobs/JobsSystemMonitor`。日志按 512 KiB 轮转，最多保留两个备份。设置使用系统用户级 `QSettings`，不写源码目录。

| 现象 | 处理 |
| --- | --- |
| CPU / 网速刚启动显示 `--` | 等待下一个刷新周期建立差分；这不是采样错误。 |
| 没有网络数据 | 刷新网卡并手动指定出口；确认网卡在线且有 IP，必要时选 VPN 虚拟网卡。 |
| GPU 一直 `--` | 查看详情中的驱动说明，点击“重新采集”；不支持时其它指标仍正常。 |
| 面板关了如何找回 | 点击菜单栏 / 托盘 / 悬浮监控条；右键监控条也有详情与退出菜单。 |
| Windows 遮挡图标 | 拖动监控条，或在详情中“重置位置”；也可关闭监控条，只保留托盘入口。 |
| 再次打开提示已运行 | 单实例保护生效，通过现有入口打开；更新前先退出旧进程。 |
| Mac 提示旧 Python 或缺少运行时 | 入口先自检 Homebrew 并更新，再准备满足版本要求的 Brew Python；必需修复回车执行，失败立即停止。 |
| Homebrew 下载提示 `curl: (35) Recv failure: Connection reset by peer` | TLS 连接阶段失败，尚未执行安装器，与 `YES` 路径选择无关。脚本会有限重试并尝试官方 API；仍失败时检查网络 / DNS 及终端代理是否可访问这两个官方域名。终端使用代理软件时，按软件提供的设置配置 `HTTPS_PROXY` / `ALL_PROXY`；脚本保留证书校验，不自动改系统代理。 |
| Homebrew 提示证书错误、HTTP 403 或安装器内容校验失败 | 检查终端证书、官方 API 限流和网络返回内容；证书错误、HTTP 403 不在同一地址反复重试。HTML / JSON 错误页、空文件和语法异常不会执行；未进入打包和旧包清理。 |
| 打包失败 | 查看终端及 `JobsSystemMonitor-build.log`；依赖失败会在清理旧包之前停止。 |

## 七、<span id="repository-layout-and-entrypoints">本仓目录与脚本入口</span> <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

以下为当前检出的源码与维护入口；依赖环境、Git 元数据、构建缓存和生成产物略去，独立子仓仅列目录。

```text
.
├── .gitignore
├── 【MacOS】📦生成dmg.command
├── 【Windows】📦生成exe.bat
├── icon.png
├── JobsSystemMonitor/
│   ├── assets/
│   ├── pyproject.toml
│   ├── scripts/
│   ├── src/
│   └── tests/
└── README.md
```

* `JobsSystemMonitor/src/` 保存系统采样、菜单栏 / 任务栏与桌面界面；`scripts/` 保存构建、启动和快捷方式辅助代码，`tests/` 保存回归用例。

<a id="🔚" href="#前言" style="font-size:17px; color:green; font-weight:bold;">我是有底线的➤点我回到首页</a>
