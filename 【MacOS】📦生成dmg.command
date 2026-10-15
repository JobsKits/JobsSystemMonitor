#!/bin/zsh
# 脚本自述：在 macOS 本机生成 Jobs System Monitor APP / DMG。
# shell: zsh
# 清理仅限当前工具 dist；先复用健康 Python 3.11+，缺失时回车确认安装。
# 仅使用已有健康 Homebrew / uv；实际打包复用内层的防误触确认。
SCRIPT_FILE="${(%):-%x}"
SCRIPT_DIR=""
LOG_FILE=""
PYTHON_BIN=""
INSTALLER_BIN=""
INSTALLER_KIND=""
# 无副作用地准备展示路径，不修改运行环境或写日志。
prepare_display_paths() {
    SCRIPT_DIR="${SCRIPT_FILE:A:h}"
    LOG_FILE="${TMPDIR:-/tmp}"
    LOG_FILE="${LOG_FILE%/}/JobsSystemMonitor-build.log"
}
# 彩色终端使用红色粗体标题和蓝色常规正文，其它环境纯文本展示。
print_intro_line() {
    local role="$1"
    local message="$2"
    if [[ -t 1 && -n "${TERM:-}" && "${TERM:-}" != dumb && -z "${NO_COLOR+x}" ]]; then
        if [[ "$role" == title ]]; then
            printf '\033[1;31m%s\033[0m\n' "$message"
        else
            printf '\033[0;34m%s\033[0m\n' "$message"
        fi
    else
        print -r -- "$message"
    fi
}
# 先展示固定自述；健康环境的构建确认统一由内层完成。
show_script_intro_and_wait() {
    prepare_display_paths
    print_intro_line title 'Jobs System Monitor · macOS 本机打包'
    print_intro_line body '1、生成状态栏监控 APP / DMG，仅清理本工具固定 dist 旧产物。'
    print_intro_line body '2、复用 Python 3.11+；缺失运行时或依赖时，直接回车安装，任意非空输入（含空格）取消。'
    print_intro_line body '3、健康依赖不升级；输出 dist/YYYY.MM.DD HH-mm-ss，验证后更新相对链接。'
    print_intro_line body '4、打开本次磁盘位置，再启动本次 APP；成功结尾不再等待。'
    print_intro_line body "日志：${LOG_FILE}；构建前由内层等待回车确认，Ctrl+C 取消。"
    if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
        print -r -- '用法：双击此脚本或在终端运行；--help 仅显示说明，无副作用。'
        exit 0
    fi
}
# 只允许 macOS 入口，避免其它平台先安装不适用的运行时。
check_platform() {
    if [[ "$(uname -s)" != Darwin ]]; then
        print -u2 -- '此入口仅支持 macOS；Windows 请运行【Windows】📦生成exe.bat。'
        exit 1
    fi
}
# 收集现有解释器，兼容旧默认 python3、版本命令、Homebrew 和官方安装位置。
python_candidates() {
    local candidate=""
    local version=""
    [[ -x "$SCRIPT_DIR/JobsSystemMonitor/.venv/bin/python" ]] && print -r -- "$SCRIPT_DIR/JobsSystemMonitor/.venv/bin/python"
    for version in python3.13 python3.12 python3.11 python3.14 python3.15 python3 python; do
        candidate="$(command -v "$version" 2>/dev/null)"
        [[ -n "$candidate" ]] && print -r -- "$candidate"
    done
    for version in 3.13 3.12 3.11 3.14 3.15; do
        for candidate in "/opt/homebrew/opt/python@${version}/bin/python${version}" "/usr/local/opt/python@${version}/bin/python${version}" "/Library/Frameworks/Python.framework/Versions/${version}/bin/python${version}"; do
            [[ -x "$candidate" ]] && print -r -- "$candidate"
        done
    done
    for candidate in "$HOME"/.local/share/uv/python/cpython-3.*-macos-*/bin/python3(N); do
        [[ -x "$candidate" ]] && print -r -- "$candidate"
    done
}
# 验证版本和构建所需标准库；旧版和损坏解释器仅跳过，不用 assert 裸退出。
find_healthy_python() {
    local candidate=""
    local detected=""
    local -A checked
    while IFS= read -r candidate; do
        [[ -z "$candidate" || -n "${checked[$candidate]:-}" ]] && continue
        checked[$candidate]=1
        detected="$(PYTHONDONTWRITEBYTECODE=1 "$candidate" -c 'import sys
print("Python " + sys.version.split()[0], flush=True)
if sys.version_info < (3, 11):
    sys.exit(2)
try:
    import venv, pathlib, tomllib
except ImportError as error:
    print("标准库不完整：" + str(error))
    sys.exit(3)' 2>&1)"
        if (( $? == 0 )); then
            PYTHON_BIN="$candidate"
            print -r -- "✔ 复用 ${detected}：${candidate}"
            return 0
        fi
        print -r -- "跳过不兼容或不可用的解释器：${candidate}（${detected:-无法启动}；需要 Python 3.11+）。"
    done < <(python_candidates)
    return 1
}
# 查找已有且可用的安装通道，不安装 Homebrew 或执行未知下载脚本。
find_runtime_installer() {
    local candidate=""
    local prefix=""
    for candidate in "$(command -v brew 2>/dev/null)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [[ -n "$candidate" && -x "$candidate" ]] || continue
        if "$candidate" --version >/dev/null 2>&1; then
            prefix="$("$candidate" --prefix 2>/dev/null)"
            if [[ -n "$prefix" && -d "$prefix" ]]; then
                INSTALLER_BIN="$candidate"
                INSTALLER_KIND=brew
                return 0
            fi
        fi
    done
    for candidate in "$(command -v uv 2>/dev/null)" "$HOME/.local/bin/uv"; do
        [[ -n "$candidate" && -x "$candidate" ]] || continue
        if "$candidate" --version >/dev/null 2>&1; then
            INSTALLER_BIN="$candidate"
            INSTALLER_KIND=uv
            return 0
        fi
    done
    return 1
}
# 运行时是必需依赖；只接受交互终端中的空行，取消和 EOF 均不写入。
confirm_runtime_install() {
    local answer=""
    print -r -- "缺少可用 Python 3.11+；将通过已有 ${INSTALLER_KIND} 安装 Python 3.13。"
    if [[ ! -t 0 ]]; then
        print -u2 -- '没有可交互输入，尚未安装或清理；请在终端重新运行。'
        exit 1
    fi
    if ! IFS= read -r 'answer?直接回车安装；输入任意字符（含空格）取消，Ctrl+C 取消：'; then
        print -u2 -- '输入已结束，尚未安装或清理。'
        exit 1
    fi
    if [[ -n "$answer" ]]; then
        print -r -- '已取消；尚未安装或清理。'
        exit 1
    fi
}
# 安装只尝试一次，立即重新验证；失败不能继续依赖安装或删除旧产物。
install_required_runtime() {
    local candidate=""
    if [[ "$INSTALLER_KIND" == brew ]]; then
        if ! HOMEBREW_NO_AUTO_UPDATE=1 "$INSTALLER_BIN" install python@3.13; then
            print -u2 -- 'Python 安装失败；请检查上方 Homebrew 错误，尚未清理旧产物。'
            exit 1
        fi
        candidate="$("$INSTALLER_BIN" --prefix python@3.13 2>/dev/null)/bin/python3.13"
    else
        if ! "$INSTALLER_BIN" python install 3.13; then
            print -u2 -- 'Python 安装失败；请检查上方 uv 错误，尚未清理旧产物。'
            exit 1
        fi
        candidate="$("$INSTALLER_BIN" --no-cache python find --managed-python --no-python-downloads 3.13 2>/dev/null)"
    fi
    if [[ -n "$candidate" ]] && PYTHONDONTWRITEBYTECODE=1 "$candidate" -c 'import sys,venv,pathlib,tomllib; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        print -r -- "✔ 新运行时验证通过：${PYTHON_BIN}"
        return 0
    fi
    print -u2 -- '安装后 Python 仍不可用，已停止；尚未清理旧产物。'
    exit 1
}
# 沿缺失分支查找安装器；没有健康安装器时给出明确的官方安装入口。
check_environment() {
    find_healthy_python && return 0
    if ! find_runtime_installer; then
        print -u2 -- '未找到可用的 Python 3.11+，也没有健康的 Homebrew / uv；尚未安装或清理。'
        print -u2 -- '请安装官方 macOS Python 3.11+ 后重新运行：https://www.python.org/downloads/macos/'
        exit 1
    fi
    confirm_runtime_install
    install_required_runtime
}
# 转交已验证解释器；内层保留实际构建和清理前的唯一防误触确认。
run_build() {
    setopt NO_NOMATCH
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" "$SCRIPT_DIR/JobsSystemMonitor/scripts/build.py" "$@"
    local build_result=$?
    if (( build_result != 0 )); then
        print -u2 -- "打包已停止；请查看上方错误和日志：${LOG_FILE}"
    fi
    exit "$build_result"
}
# 编排自述、运行时检查和构建，不在解释器检查阶段清理旧产物。
main() {
    show_script_intro_and_wait "$@" # 首屏展示范围；内层负责构建防误触确认。
    check_platform # 安装和清理前先拒绝不适用的平台。
    check_environment # 复用健康运行时；缺失分支交互确认后安装并复检。
    run_build "$@" # 生成、验证、定位并启动本次 APP，透传参数。
}
main "$@"
