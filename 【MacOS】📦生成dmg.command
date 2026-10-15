#!/bin/zsh
# 脚本自述：在 macOS 本机生成 Jobs System Monitor APP / DMG。
# shell: zsh
# 清理仅限当前工具 dist；先复用健康 Python 3.11+，缺失时回车确认安装。
# Homebrew 自检更新和 Python 修复复用随仓公共模块；实际打包由内层确认。
SCRIPT_FILE="${(%):-%x}"
SCRIPT_DIR=""
LOG_FILE=""
PYTHON_BIN=""
# 无副作用地准备展示路径，不修改运行环境或写日志。
prepare_display_paths() {
    SCRIPT_DIR="${${functions_source[prepare_display_paths]}:A:h}"
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
    print_intro_line body '2、先更新或安装 Homebrew，再准备其管理的 Python 3.11+；缺失依赖回车安装。'
    print_intro_line body '3、Python 满足要求时不升级；任意非空输入取消安装；输出 dist/YYYY.MM.DD HH-mm-ss，验证后更新相对链接。'
    print_intro_line body '4、打开本次磁盘位置，再启动本次 APP；成功结尾不再等待。'
    print_intro_line body "日志：${LOG_FILE}；环境准备与内层构建分别等待回车确认，Ctrl+C 取消。"
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
# 通过随仓交付的公共模块准备 Homebrew 与兼容的 Python。
prepare_python_runtime() {
  local definition_file="${functions_source[prepare_python_runtime]}"
  local runtime="${definition_file:A:h}/HomebrewSupport/python-runtime.zsh"
  [[ -f "$runtime" ]] || { print -u2 -- "缺少公共环境模块：$runtime"; exit 1; }
  source "$runtime" || exit 1
  jobs_python_confirm_prepare "将更新 Homebrew，并检查本工具的 Python 环境" || exit 1
  jobs_python_ensure 3.11 python@3.13 || exit 1
}
# 在构建前完成公共运行时自检。
check_environment() {
    prepare_python_runtime
    PYTHON_BIN="$JOBS_PYTHON_BIN"
    if [[ -e "$SCRIPT_DIR/JobsSystemMonitor/.venv" || -L "$SCRIPT_DIR/JobsSystemMonitor/.venv" ]]; then
        jobs_python_prepare_venv "$SCRIPT_DIR/JobsSystemMonitor/.venv" 3.11 || exit 1
    fi
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
