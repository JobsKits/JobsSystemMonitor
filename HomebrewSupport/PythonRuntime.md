# <span id="前言">Python 公共环境自检</span>

![Jobs出品，必属精品](https://picsum.photos/1500/400)

[toc]

---

## 🔥 前言

[**macOS**](https://www.apple.com/macos/) 的 [**Python**](https://www.python.org) 入口统一调用 `./python-runtime.zsh`，它复用同目录 `./install-homebrew.zsh`，不依赖父仓、硬编码用户名或系统旧解释器。仅 `source` 不探测环境、不联网、不改进程选项；入口先显示自述并确认，再调用公共接口。

## 一、完整流程 <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

1、确认后的交互进程自检 [**Homebrew**](https://brew.sh/)，已有安装执行 `brew update` 更新本体与配方索引，失败立即停止；不执行全量 `brew upgrade`。同一进程重复调用只在首次成功时更新。命令语义见 [Homebrew 官方说明](https://docs.brew.sh/Manpage#update-options)。

2、缺少 Homebrew 时选择安装路径：精确输入 `YES` 选择系统标准目录；其它输入或直接回车选择用户目录。系统权限由官方安装器处理；用户路线不使用 sudo。失败不改换路线，不覆盖非空目标。新系统缺少 Command Line Tools 时，按提示完成系统安装后重新运行。

3、实际检查指定 Brew 配方的 Python 路径归属、最低版本、可选上限和标准库；默认 `python@3.13`、最低 3.11。健康环境复用；缺失、旧版或损坏时只处理该 Python 配方，直接回车执行必需修复，任何非空输入（含空格）取消。安装和复检失败均停止。

4、仅需创建 / 复用项目虚拟环境的入口调用 `jobs_python_prepare_venv`。健康环境复用，旧坏环境经确认完整改名备份后重建，备份保留；普通项目目录、空路径、根目录、符号链接和非目录不作为虚拟环境修复目标。

非交互 / Sourcetree 入口只读检查已有健康环境；缺失或不兼容时明确停止，先在终端准备。无输入、EOF、取消都不能当成安装确认。业务失败不会回落至系统 Python 或 uv。Windows 保持各自平台的原环境流程；已打包成品包含运行时，无需执行本模块。

## 二、公共接口 <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

```zsh
# 在入口函数内按脚本位置 source；此路径示例适用于模块与入口同属一个根目录。
source "$SCRIPT_DIR/HomebrewSupport/python-runtime.zsh" || exit 1
jobs_python_mark_confirmed || exit 1 # 已有自述确认后调用，不重复读取输入。
jobs_python_ensure 3.11 python@3.13 || exit 1
"$JOBS_PYTHON_BIN" "$SCRIPT_DIR/app.py"
```

| 接口 | 用途 |
| --- | --- |
| `jobs_python_confirm_prepare [说明]` | 自述后尚未确认时，确认本次更新与准备环境。 |
| `jobs_python_mark_confirmed` | 已由入口完成回车确认时标记当前进程，不依赖继承环境绕过确认。 |
| `jobs_python_ensure MIN [FORMULA] [MAX]` | `MAX` 为排他上限；例如 `3.10 python@3.12 3.13` 保留语音工具兼容范围。 |
| `jobs_python_prepare_venv ENV_DIR MIN [MAX]` | 在成功 ensure 后创建或复用虚拟环境，按版本要求修复。 |

成功输出 `JOBS_PYTHON_BIN` 并刷新当前进程 PATH，不覆盖消费者已有的 `PYTHON_BIN` 虚拟环境变量。不要用命令替换调用 ensure，否则进程内环境变更无法传回；用明确解释器变量或确认后的 PATH 调用 Python。

## 三、维护与验证 <a href="#前言" style="font-size:17px; color:green;"><b>🔼</b></a> <a href="#🔚" style="font-size:17px; color:green;"><b>🔽</b></a>

JobsGenesis 根的本目录是公共源码来源。独立仓库携带完全相同的受控副本，保障单独克隆；修改公共库后在总仓运行 `./sync-python-runtime.command` 同步，再执行 `./sync-python-runtime.command --check` 核对。接入清单、目标列表及隔离测试仅由总仓维护，不要求运行工具的机器装齐其它仓库。

验证使用假 Homebrew、临时 HOME 和终端模拟，不真实安装 / 升级软件；覆盖更新失败、版本上下限、解释器归属、取消 / EOF、路径含空格、虚拟环境备份及复检。全新系统的安装对话框、网络与包源仍需目标机器验收。

<a id="🔚" href="#前言" style="font-size:17px; color:green; font-weight:bold;">我是有底线的➤点我回到首页</a>
