"""macOS 薄入口的运行时发现与安装门禁；全部使用隔离假命令。Created by Jobs."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

try:
    import pty
except ImportError:
    pty = None

ENTRY = Path(__file__).resolve().parents[2] / '【MacOS】📦生成dmg.command'


@unittest.skipUnless(shutil.which('zsh') and os.name == 'posix', 'Requires zsh and POSIX PTY.')
class MacRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.project = self.base / '监控 克隆目录'
        self.project.mkdir()
        self.marker = self.base / 'install-writes'
        self.installed = self.base / 'installed'
        self.zsh = shutil.which('zsh')
        self.env = dict(os.environ, PATH=str(self.bin), HOME=str(self.base),
                        INSTALL_WRITES=str(self.marker), INSTALL_PREFIX=str(self.installed),
                        BREW_PREFIX=str(self.base), NO_COLOR='1')
        # 重定位系统级发现路径，避免把测试机的真实 Python / 安装器当作测试依赖。
        source = ENTRY.read_text(encoding='utf-8').rsplit('main "$@"', 1)[0]
        for prefix in ('/opt/homebrew', '/usr/local', '/Library/Frameworks'):
            source = source.replace(prefix, str(self.base / ('absent-' + prefix.rsplit('/', 1)[1])))
        self.source = source + '\nprepare_display_paths\nSCRIPT_DIR=' + shlex.quote(str(self.project)) + '\n'

    def tearDown(self):
        self.temp.cleanup()

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!' + self.zsh + '\n' + body + '\n', encoding='utf-8')
        path.chmod(0o755)
        return path

    def python(self, name, version='3.13.1', healthy=True):
        return self.command(name, 'print -r -- "Python ' + version + '"\nexit ' + ('0' if healthy else '2'))

    def brew(self, install_result=0):
        return self.command('brew', '''case "$1" in
--version) print -r -- 'Homebrew fake' ;;
--prefix) [[ $# == 1 ]] && print -r -- "$BREW_PREFIX" || print -r -- "$INSTALL_PREFIX" ;;
install) print -r -- "$*" >> "$INSTALL_WRITES"; exit %s ;;
*) exit 2 ;;
esac''' % install_result)

    def invoke(self, action='check_environment; print -r -- "SELECTED=$PYTHON_BIN"', answer=None):
        command = [self.zsh, '-f', '-c', self.source + '\n' + action]
        if answer is None:
            return subprocess.run(command, env=self.env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=10)
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(command, env=self.env, stdin=slave,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            os.write(master, answer)
            output, error = process.communicate(timeout=10)
            return subprocess.CompletedProcess(command, process.returncode, output, error)
        finally:
            os.close(slave)
            os.close(master)

    def test_versioned_python_is_found_when_default_is_old(self):
        self.python('python3', '3.9.6', healthy=False)
        expected = self.python('python3.12', '3.12.9')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SELECTED=' + str(expected), result.stdout)
        self.assertFalse(self.marker.exists())

    def test_old_default_version_is_reported_without_traceback(self):
        self.python('python3', '3.9.6', healthy=False)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python 3.9.6', result.stdout)
        self.assertIn('3.11+', result.stdout)
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        self.assertNotIn('AssertionError', result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())

    def test_absent_runtime_and_manager_print_official_install_guidance(self):
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('https://www.python.org/downloads/macos/', result.stderr)
        self.assertIn('尚未安装或清理', result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.project / 'dist').exists())

    def test_missing_runtime_with_no_tty_never_installs(self):
        self.brew()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('没有可交互输入', result.stderr)
        self.assertFalse(self.marker.exists())

    @unittest.skipIf(pty is None, 'Requires POSIX PTY.')
    def test_missing_runtime_rejects_any_nonempty_answer_including_space(self):
        self.brew()
        for answer in (b'cancel\n', b' \n'):
            with self.subTest(answer=answer):
                result = self.invoke(answer=answer)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('已取消', result.stdout)
                self.assertFalse(self.marker.exists())
                self.assertFalse((self.project / 'dist').exists())

    @unittest.skipIf(pty is None, 'Requires POSIX PTY.')
    def test_missing_runtime_eof_does_not_install(self):
        self.brew()
        result = self.invoke(answer=b'\x04')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('输入已结束', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_healthy_runtime_does_not_probe_or_install_manager(self):
        self.python('python3.13')
        self.command('brew', 'print -r -- "$*" >> "$INSTALL_WRITES"; exit 0')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('复用 Python 3.13.1', result.stdout)
        self.assertFalse(self.marker.exists())

    @unittest.skipIf(pty is None, 'Requires POSIX PTY.')
    def test_accepted_brew_install_rechecks_exact_new_runtime(self):
        self.brew()
        executable = self.installed / 'bin/python3.13'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!' + self.zsh + '\nexit 0\n', encoding='utf-8')
        executable.chmod(0o755)
        result = self.invoke(answer=b'\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'install python@3.13\n')
        self.assertIn('SELECTED=' + str(executable), result.stdout)
        self.assertFalse((self.project / 'dist').exists())

    @unittest.skipIf(pty is None, 'Requires POSIX PTY.')
    def test_install_failure_stops_without_build_or_cleanup(self):
        self.brew(install_result=7)
        result = self.invoke(answer=b'\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('安装失败', result.stderr)
        self.assertNotIn('SELECTED=', result.stdout)
        self.assertFalse((self.project / 'dist').exists())

    @unittest.skipIf(pty is None, 'Requires POSIX PTY.')
    def test_postinstall_unhealthy_runtime_stops(self):
        self.brew()
        result = self.invoke(answer=b'\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('安装后 Python 仍不可用', result.stderr)
        self.assertNotIn('SELECTED=', result.stdout)
        self.assertFalse((self.project / 'dist').exists())

    @unittest.skipIf(pty is None, 'Requires POSIX PTY.')
    def test_existing_uv_is_an_alternative_install_channel(self):
        executable = self.installed / 'bin/python3.13'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!' + self.zsh + '\nexit 0\n', encoding='utf-8')
        executable.chmod(0o755)
        self.command('uv', '''case "$*" in
--version) print -r -- 'uv fake' ;;
'python install 3.13') print -r -- "$*" >> "$INSTALL_WRITES" ;;
'--no-cache python find --managed-python --no-python-downloads 3.13') print -r -- "$INSTALL_PREFIX/bin/python3.13" ;;
*) exit 2 ;;
esac''')
        result = self.invoke(answer=b'\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SELECTED=' + str(executable), result.stdout)
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'python install 3.13\n')

    def test_unsupported_platform_never_installs(self):
        self.command('uname', 'print -r -- Linux')
        self.brew()
        result = self.invoke(action='check_platform; check_environment')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('仅支持 macOS', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_help_has_no_runtime_checks_or_writes(self):
        result = self.invoke(action='show_script_intro_and_wait --help; check_environment')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--help 仅显示说明', result.stdout)
        self.assertNotIn('未找到', result.stderr)
        self.assertFalse(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
