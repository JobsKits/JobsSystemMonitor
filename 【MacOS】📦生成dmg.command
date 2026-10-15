#!/bin/zsh
# 脚本自述：在 macOS 本机生成 Jobs System Monitor APP / DMG。
# shell: zsh
# 清理仅限当前工具 dist；缺失依赖由内层回车确认安装，健康依赖复用。
# 薄转发入口复用内层构建器的防误触确认；成功后定位并启动本次 APP。
SCRIPT_FILE="${(%):-%x}"
SCRIPT_DIR=""
LOG_FILE=""
# 无副作用地准备展示路径，并识别 help；不修改运行环境或写日志。
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
# 先展示固定内置自述；实际确认统一由内层完成，避免转发入口重复等待。
show_script_intro_and_wait() {
    prepare_display_paths
    print_intro_line title 'Jobs System Monitor · macOS 本机打包'
    print_intro_line body '1、生成状态栏监控 APP / DMG，仅清理本工具固定 dist 旧产物。'
    print_intro_line body '2、缺失依赖回车安装；任意非空输入（含空格）取消；健康依赖不升级。'
    print_intro_line body '3、输出 dist/YYYY.MM.DD HH-mm-ss；验证后更新 APP / DMG 相对链接。'
    print_intro_line body '4、打开本次磁盘位置，再启动本次 APP；成功结尾不再等待。'
    print_intro_line body "日志：${LOG_FILE}；下一步由内层统一等待回车确认，Ctrl+C 取消。"
    if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
        print -r -- '用法：双击此脚本或在终端运行；--help 仅显示说明，无副作用。'
        exit 0
    fi
}
# 验证 Python 运行时；依赖安装与输出清理由内层确认后执行。
check_environment() {
    command -v python3 >/dev/null || {
        print -u2 -- '请安装 Python 3.11+：https://www.python.org/downloads/'
        exit 1
    }
    python3 -c 'import sys,venv,pathlib; assert sys.version_info >= (3,11)' || exit 1
}
# 转交构建器；原生 zsh 选项只在独立函数内设置，不散落顶层。
run_build() {
    setopt NO_NOMATCH
    PYTHONDONTWRITEBYTECODE=1 python3 "$SCRIPT_DIR/JobsSystemMonitor/scripts/build.py" "$@"
    local build_result=$?
    if (( build_result != 0 )); then
        print -u2 -- "打包已停止；请查看上方错误和日志：${LOG_FILE}"
    fi
    exit "$build_result"
}
# 编排薄转发入口；真实安装、清理及构建先经过内层回车确认。
main() {
    show_script_intro_and_wait "$@" # 首屏展示范围；内层负责唯一一次防误触确认。
    check_environment # 确认现有 Python 运行时可用，不安装或升级系统软件。
    run_build "$@" # 生成、验证、定位并启动本次 APP，透传 help 等参数。
}
main "$@"
