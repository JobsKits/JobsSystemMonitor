#!/usr/bin/env python3
"""脚本内嵌 Homebrew 安装路径选择隔离回归；所有下载、Git 和安装器均为假命令。"""
import errno
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

try:
    import pty
except ImportError:
    pty = None

ENTRY = Path(__file__).resolve().parents[2] / '【MacOS】📦生成dmg.command'
BLOCK_MARKERS = (
    ('# >>> Jobs Homebrew install choice >>>', '# <<< Jobs Homebrew install choice <<<'),
    ('# >>> Jobs embedded Python runtime >>>', '# <<< Jobs embedded Python runtime <<<'),
)


def embedded_environment_source():
    """从真实交付脚本抽取内嵌函数，不读取任何仓外环境模块。"""
    source = ENTRY.read_text(encoding='utf-8')
    blocks = []
    for start, end in BLOCK_MARKERS:
        first = source.index(start)
        last = source.index(end, first) + len(end)
        blocks.append(source[first:last])
    return '\n'.join(blocks) + '\n'

ZSH = '/bin/zsh'


@unittest.skipUnless(Path(ZSH).exists() and pty and os.name == 'posix', 'Requires zsh and POSIX PTY.')
class BrewChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jobs-brew-choice-test-')
        self.root = Path(self.temp.name).resolve()
        self.core = self.root / '独立 Homebrew 🫡.zsh'
        self.core.write_text(embedded_environment_source(), encoding='utf-8')
        self.home = self.root / 'home'
        self.mockbin = self.root / 'bin'
        self.template = self.root / 'brew-template'
        for directory in [self.home, self.mockbin, self.template / 'bin']:
            directory.mkdir(parents=True)
        self.log = self.root / 'calls.log'
        self.log.touch()
        self._write_executable(self.template / 'bin' / 'brew', r'''#!/bin/zsh
prefix="${0:A:h:h}"
print -r -- "brew:$1:NO_SUDO=${HOMEBREW_NO_SUDO:-unset}" >> "$MOCK_LOG"
case "$1" in
  --version) print -r -- 'Homebrew test' ;;
  --prefix) print -r -- "$prefix" ;;
  shellenv) printf 'export PATH=%q:$PATH\n' "$prefix/bin" ;;
  config) [[ "${MOCK_CONFIG_FAIL:-0}" != 1 ]] ;;
  *) exit 2 ;;
esac
''')
        self._write_executable(self.mockbin / 'curl', r'''#!/bin/zsh
print -r -- "curl:NO_SUDO=${HOMEBREW_NO_SUDO:-unset}:$*" >> "$MOCK_LOG"
while (( $# )); do
  if [[ "$1" == -o ]]; then
    destination="$2"
    shift 2
  elif [[ "$1" == https://* ]]; then
    source_url="$1"
    shift
  else
    shift
  fi
done
case "$source_url" in
  */install/HEAD/install.sh) cp "$MOCK_INSTALLER" "$destination" ;;
  */releases/latest) print -r -- '{"tag_name":"7.0.9"}' > "$destination" ;;
  *) exit 97 ;;
esac
''')
        self._write_executable(self.mockbin / 'git', r'''#!/bin/zsh
print -r -- "git:NO_SUDO=${HOMEBREW_NO_SUDO:-unset}:$*" >> "$MOCK_LOG"
[[ "$1" != --version ]] || { print -r -- 'git version mock'; exit 0; }
for item in "$@"; do
  if [[ "$item" == clone ]]; then
    cp -R "$MOCK_TEMPLATE" "${@[-1]}"
    exit 0
  fi
done
exit 0
''')
        self._write_executable(self.mockbin / 'sudo', r'''#!/bin/zsh
print -r -- 'SUDO_TRAP' >> "$MOCK_LOG"
exit 96
''')
        self.installer = self.root / 'installer.sh'
        self._write_executable(self.installer, r'''#!/bin/bash
printf 'installer:NO_SUDO=%s:NONINTERACTIVE=%s\n' "${HOMEBREW_NO_SUDO:-unset}" "${NONINTERACTIVE:-unset}" >> "$MOCK_LOG"
[[ "${MOCK_INSTALL_FAIL:-0}" != 1 ]] || exit 23
cp -R "$MOCK_TEMPLATE" "$MOCK_SYSTEM_PREFIX"
''')
        self.env = {
            'HOME': str(self.home), 'SHELL': ZSH, 'TERM': 'xterm-256color',
            'PATH': f'{self.mockbin}:/usr/bin:/bin:/usr/sbin:/sbin',
            'TMPDIR': str(self.root) + '/', 'MOCK_ROOT': str(self.root),
            'MOCK_LOG': str(self.log), 'MOCK_TEMPLATE': str(self.template),
            'MOCK_INSTALLER': str(self.installer),
            'MOCK_SYSTEM_PREFIX': str(self.root / 'system'),
        }
        self.prefix = f'''source {str(self.core)!r}
functions[jobs_brew_candidate_original]=$functions[jobs_brew_candidate_ok]
jobs_brew_candidate_ok() {{
  [[ "$1" == "$MOCK_ROOT/"* ]] || return 1
  jobs_brew_candidate_original "$1"
}}
jobs_brew_system_prefix() {{ print -r -- "$MOCK_SYSTEM_PREFIX"; }}
'''

    def tearDown(self):
        # Restore directory access so readonly-install fixtures can be removed.
        for directory, dirs, files in os.walk(self.root):
            os.chmod(directory, 0o755)
        self.temp.cleanup()

    @staticmethod
    def _write_executable(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_pipe(self, code, env=None):
        process_env = self.env | (env or {})
        return subprocess.run([ZSH, '-f', '-c', self.prefix + code], env=process_env,
                              input='', text=True, capture_output=True, timeout=10)

    def run_tty(self, code, answer=b'\n', env=None):
        process_env = self.env | (env or {})
        pid, master = pty.fork()
        if pid == 0:
            os.execve(ZSH, [ZSH, '-f', '-c', self.prefix + code], process_env)
        output = bytearray()
        answered = False
        deadline = time.monotonic() + 10
        wait_status = None
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b''
                    if chunk:
                        output.extend(chunk)
                        if not answered and '➤ 安装路径选择：'.encode() in output:
                            os.write(master, answer)
                            answered = True
                waited, status = os.waitpid(pid, os.WNOHANG)
                if waited:
                    wait_status = status
                    break
            if wait_status is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                raise AssertionError('PTY process timed out: ' + output.decode(errors='replace'))
            # Drain output queued immediately before process completion.
            while select.select([master], [], [], 0)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            return os.waitstatus_to_exitcode(wait_status), output.decode(errors='replace')
        finally:
            os.close(master)

    def calls(self):
        return self.log.read_text()

    def install_existing(self):
        existing = self.root / 'existing'
        shutil.copytree(self.template, existing)
        return existing

    def test_exact_yes_chooses_official_system_path(self):
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'YES\n')
        self.assertEqual(code, 0, output)
        self.assertIn('BUSINESS_REACHED', output)
        self.assertIn('installer:NO_SUDO=unset:NONINTERACTIVE=unset', self.calls())
        self.assertNotIn('git:', self.calls())
        self.assertFalse((self.home / '.local/homebrew').exists())

    def test_return_chooses_user_path_without_sudo(self):
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED')
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / '.local/homebrew/bin/brew').exists())
        self.assertIn('git:NO_SUDO=1:', self.calls())
        self.assertIn('brew:config:NO_SUDO=1', self.calls())
        self.assertNotIn('installer:', self.calls())
        self.assertNotIn('SUDO_TRAP', self.calls())

    def test_nonexact_yes_always_chooses_user_path(self):
        for answer in [b'yes\n', b' YES\n', b'YES \n', b'NO\n']:
            with self.subTest(answer=answer):
                code, output = self.run_tty('jobs_brew_choose_installation; print -r -- "MODE:$JOBS_HOMEBREW_INSTALL_MODE"', answer)
                self.assertEqual(code, 0, output)
                self.assertIn('MODE:user', output)
        self.assertEqual(self.calls(), '')

    def test_eof_stops_entire_install(self):
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'\x04')
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertEqual(self.calls(), '')

    def test_ctrl_c_stops_entire_install(self):
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'\x03')
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertEqual(self.calls(), '')

    def test_noninteractive_missing_brew_fails_without_install(self):
        result = self.run_pipe('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('可交互终端', result.stderr)
        self.assertNotIn('BUSINESS_REACHED', result.stdout)
        self.assertEqual(self.calls(), '')

    def test_system_failure_never_falls_back(self):
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'YES\n', {'MOCK_INSTALL_FAIL': '1'})
        self.assertNotEqual(code, 0, output)
        self.assertIn('退出码 23', output)
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertNotIn('git:', self.calls())
        self.assertFalse((self.home / '.local/homebrew').exists())

    def test_existing_healthy_brew_reused_without_choice_or_profile_write(self):
        existing = self.install_existing()
        result = self.run_pipe('jobs_brew_install_or_exit; print -r -- "BREW:$JOBS_HOMEBREW_BIN"', {'JOBS_HOMEBREW_BIN': str(existing / 'bin/brew')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(existing / 'bin/brew'), result.stdout)
        self.assertNotIn('安装路径选择', result.stderr)
        self.assertNotIn('curl:', self.calls())
        self.assertFalse((self.home / '.zprofile').exists())

    def test_readonly_existing_brew_is_reused(self):
        existing = self.install_existing()
        for directory, dirs, files in os.walk(existing):
            os.chmod(directory, 0o555)
        result = self.run_pipe('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', {'JOBS_HOMEBREW_BIN': str(existing / 'bin/brew')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('BUSINESS_REACHED', result.stdout)
        self.assertNotIn('curl:', self.calls())
        self.assertFalse((self.home / '.local').exists())

    def test_profile_idempotent_symlink_preserved_and_reload_works(self):
        existing = self.install_existing()
        actual = self.home / 'real-profile'
        actual.write_text('# User config\nexport JOBS_USER_SETTING=preserved\n')
        actual.chmod(0o640)
        profile = self.home / '.zprofile'
        profile.symlink_to(actual)
        code = '''JOBS_HOMEBREW_INSTALL_MODE=user
jobs_brew_save_shellenv
cp "$HOME/.zprofile" "$HOME/first-profile"
jobs_brew_save_shellenv
cmp "$HOME/.zprofile" "$HOME/first-profile"
'''
        result = self.run_pipe(code, {'JOBS_HOMEBREW_BIN': str(existing / 'bin/brew')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(profile.is_symlink())
        self.assertEqual(actual.stat().st_mode & 0o777, 0o640)
        self.assertIn('export JOBS_USER_SETTING=preserved', actual.read_text())
        self.assertEqual(actual.read_text().count('# >>> Jobs Homebrew shellenv >>>'), 1)
        self.assertNotIn('HOMEBREW_NO_SUDO', actual.read_text())
        reload_result = self.run_pipe('source "$HOME/.zprofile"; print -r -- "$JOBS_USER_SETTING:${HOMEBREW_NO_SUDO:-unset}:$(command -v brew)"')
        self.assertEqual(reload_result.returncode, 0, reload_result.stdout + reload_result.stderr)
        self.assertIn('preserved:unset:' + str(existing / 'bin/brew'), reload_result.stdout)

    def test_nonempty_user_target_is_never_overwritten(self):
        target = self.home / '.local/homebrew'
        target.mkdir(parents=True)
        keep = target / 'keep.txt'
        keep.write_text('keep')
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED')
        self.assertNotEqual(code, 0, output)
        self.assertEqual(keep.read_text(), 'keep')
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertNotIn('git:', self.calls())

    def test_empty_user_target_can_be_installed(self):
        (self.home / '.local/homebrew').mkdir(parents=True)
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED')
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / '.local/homebrew/bin/brew').exists())

    def test_ruby_config_failure_stops_without_profile_write(self):
        code, output = self.run_tty('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', env={'MOCK_CONFIG_FAIL': '1'})
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertFalse((self.home / '.zprofile').exists())

    def test_explicit_system_environment_is_preserved(self):
        code, output = self.run_tty('jobs_brew_install_or_exit', b'YES\n', {'HOMEBREW_NO_SUDO': '1', 'NONINTERACTIVE': '1'})
        self.assertEqual(code, 0, output)
        self.assertIn('installer:NO_SUDO=1:NONINTERACTIVE=1', self.calls())

    def test_dry_run_prints_paths_without_read_or_install(self):
        result = self.run_pipe('jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', {'DRY_RUN': '1'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('系统路径', result.stderr)
        self.assertIn(str(self.home / '.local/homebrew'), result.stderr)
        self.assertEqual(self.calls(), '')
        self.assertFalse((self.home / '.zprofile').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
