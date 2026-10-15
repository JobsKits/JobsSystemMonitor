"""Jobs System Monitor 的源码 / 打包应用入口。Created by Jobs."""
from pathlib import Path
import sys


def main():
    """在源码环境补齐导入路径，再交给应用入口。"""
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from jobs_system_monitor.app import main as application_main
    return application_main()


if __name__ == '__main__':
    raise SystemExit(main())
