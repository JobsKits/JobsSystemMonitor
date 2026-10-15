"""macOS 入口与公共环境模块之间的集成约束；不安装、不构建。Created by Jobs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ENTRY = Path(__file__).resolve().parents[2] / '【MacOS】📦生成dmg.command'


@unittest.skipUnless(shutil.which('zsh') and os.name == 'posix', 'Requires zsh.')
class MacRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / '另一台电脑 🫡 克隆'
        self.project.mkdir()
        self.entry = self.project / ENTRY.name
        self.entry.write_text(ENTRY.read_text(encoding='utf-8'), encoding='utf-8')
        support = self.project / 'HomebrewSupport'
        support.mkdir()
        self.trace = self.base / 'trace'
        self.python = self.base / 'brew-python'
        self.python.write_text('#!/bin/zsh\nprint -r -- "BUILD:$*" >> "$TRACE"\nexit "${BUILD_RESULT:-0}"\n', encoding='utf-8')
        self.python.chmod(0o755)
        (support / 'python-runtime.zsh').write_text('''# Fake only the external module boundary.
jobs_python_confirm_prepare() { print -r -- CONFIRM >> "$TRACE"; return "${CONFIRM_RESULT:-0}"; }
jobs_python_ensure() { print -r -- "ENSURE:$*" >> "$TRACE"; export JOBS_PYTHON_BIN="$FAKE_PYTHON"; return "${ENSURE_RESULT:-0}"; }
''', encoding='utf-8')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        uname = self.bin / 'uname'
        uname.write_text('#!/bin/zsh\nprint -r -- "${FAKE_PLATFORM:-Darwin}"\n', encoding='utf-8')
        uname.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin), NO_COLOR='1', TRACE=str(self.trace), FAKE_PYTHON=str(self.python))

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *arguments, **overrides):
        return subprocess.run([shutil.which('zsh'), str(self.entry), *arguments],
                              env=dict(self.env, **overrides), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=10)

    def test_renamed_clone_uses_shared_runtime_before_build(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace.read_text(encoding='utf-8').splitlines()
        self.assertEqual(trace[:2], ['CONFIRM', 'ENSURE:3.11 python@3.13'])
        self.assertEqual(trace[2], 'BUILD:' + str(self.project / 'JobsSystemMonitor/scripts/build.py'))
        self.assertFalse((self.project / 'dist').exists())

    def test_environment_cancellation_never_builds(self):
        result = self.invoke(CONFIRM_RESULT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.trace.read_text(encoding='utf-8').splitlines(), ['CONFIRM'])

    def test_environment_failure_stops_before_build(self):
        result = self.invoke(ENSURE_RESULT='7')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('BUILD:', self.trace.read_text(encoding='utf-8'))

    def test_help_never_loads_or_updates_environment(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.trace.exists())

    def test_build_failure_is_preserved(self):
        result = self.invoke(BUILD_RESULT='9')
        self.assertEqual(result.returncode, 9)
        self.assertIn('打包已停止', result.stderr)

    def test_missing_module_reports_error_without_build(self):
        (self.project / 'HomebrewSupport/python-runtime.zsh').unlink()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('缺少公共环境模块', result.stderr)
        self.assertFalse(self.trace.exists())

    def test_other_platform_stops_before_environment(self):
        result = self.invoke(FAKE_PLATFORM='Linux')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('仅支持 macOS', result.stderr)
        self.assertFalse(self.trace.exists())


if __name__ == '__main__':
    unittest.main()
