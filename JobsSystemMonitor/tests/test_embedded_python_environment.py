#!/usr/bin/env python3
"""脚本内嵌 Python 预检隔离回归；假 Homebrew / 解释器不联网、不安装真实软件。"""
import errno
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import signal
import subprocess
import sys
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

ZSH = shutil.which('zsh')


@unittest.skipUnless(ZSH and pty and os.name == 'posix', 'Requires zsh and POSIX PTY.')
class PythonRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jobs-python-runtime-test-')
        self.root = Path(self.temp.name).resolve()
        self.core = self.root / '独立 内嵌环境 🫡.zsh'
        self.core.write_text(embedded_environment_source(), encoding='utf-8')
        self.home = self.root / 'home'
        self.mockbin = self.root / 'bin'
        self.brew_root = self.root / 'brew'
        self.cellar = self.brew_root / 'Cellar'
        self.formula = self.cellar / 'python@3.13' / '3.13.9'
        self.opt = self.brew_root / 'opt' / 'python@3.13'
        self.log = self.root / 'calls.log'
        self.state = self.root / 'runtime.json'
        self.template = self.root / 'python-template'
        for directory in (self.home, self.mockbin, self.formula / 'bin', self.opt.parent):
            directory.mkdir(parents=True, exist_ok=True)
        self.opt.symlink_to(self.formula, target_is_directory=True)
        self.log.touch()
        self.set_state()
        self.write_executable(self.template, '#!' + sys.executable + '\n' + r'''
import builtins, json, os, pathlib, shutil, sys
state = json.loads(pathlib.Path(os.environ['MOCK_STATE']).read_text())
args = sys.argv[1:]
executable = pathlib.Path(sys.argv[0]).resolve()
venv_root = executable.parent.parent
venv_state = venv_root / '.mock-runtime.json'
if venv_state.exists():
    state.update(json.loads(venv_state.read_text()))
if '-m' in args and args[args.index('-m') + 1] == 'venv':
    destination = pathlib.Path(args[-1])
    with open(os.environ['MOCK_LOG'], 'a') as stream:
        stream.write('python:venv:' + str(destination) + '\n')
    if os.environ.get('MOCK_VENV_FAIL') == '1':
        raise SystemExit(31)
    (destination / 'bin').mkdir(parents=True)
    shutil.copyfile(os.environ['MOCK_TEMPLATE'], destination / 'bin/python')
    (destination / 'bin/python').chmod(0o755)
    (destination / 'bin/python3').symlink_to('python')
    (destination / 'pyvenv.cfg').write_text('home = mock\n')
    (destination / '.mock-runtime.json').write_text(json.dumps({'version': state['version'], 'venv': True, 'broken': ''}))
    raise SystemExit(0)
if '-c' not in args:
    raise SystemExit(91)
index = args.index('-c')
code = args[index + 1]
sys.argv = ['-c'] + args[index + 2:]
sys.version_info = tuple(int(piece) for piece in state['version'].split('.')) + ('final', 0)
sys.executable = str(executable)
sys.prefix = str(venv_root if state.get('venv') else pathlib.Path(os.environ['MOCK_FORMULA']))
sys.base_prefix = str(pathlib.Path(os.environ['MOCK_FORMULA']))
original_import = builtins.__import__
def checked_import(name, *args, **kwargs):
    if state.get('broken') and name == state['broken']:
        raise ImportError('mock damaged standard library: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import
exec(compile(code, '<runtime-probe>', 'exec'), {'__name__': '__main__'})
''')
        self.install_python()
        self.brew_bin = self.brew_root / 'bin' / 'brew'
        self.brew_bin.parent.mkdir(parents=True)
        self.write_executable(self.brew_bin, '#!' + sys.executable + '\n' + r'''
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ['MOCK_BREW_ROOT'])
state_file = pathlib.Path(os.environ['MOCK_STATE'])
state = json.loads(state_file.read_text())
with open(os.environ['MOCK_LOG'], 'a') as stream:
    stream.write('brew:' + ' '.join(args) + '\n')
if args == ['--version']:
    print('Homebrew isolated test')
elif args and args[0] == '--cellar':
    print(root / 'Cellar' / ('python@3.13' if args[1] == 'python' else args[1]) if len(args) > 1 else root / 'Cellar')
elif args and args[0] == '--prefix':
    if len(args) == 1:
        print(root)
    elif state.get('available', True) or os.environ.get('MOCK_MISSING_PREFIX_RETURN') == '1':
        print(root / 'opt' / ('python@3.13' if args[1] == 'python' else args[1]))
    else:
        raise SystemExit(1)
elif args and args[0] in ('list', 'info'):
    if not state.get('available', True):
        raise SystemExit(1)
    print('python@3.13 ' + state['version'])
elif args and args[0] == 'update':
    raise SystemExit(int(os.environ.get('MOCK_UPDATE_FAIL', '0')))
elif args and args[0] in ('install', 'upgrade', 'reinstall'):
    if os.environ.get('MOCK_MUTATION_FAIL') == '1':
        raise SystemExit(23)
    if os.environ.get('MOCK_REPAIR_STILL_BROKEN') != '1':
        state.update(version=os.environ.get('MOCK_TARGET_VERSION', '3.13.9'), broken='', available=True)
        state_file.write_text(json.dumps(state))
        target = pathlib.Path(os.environ['MOCK_FORMULA']) / 'bin/python3.13'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.environ['MOCK_TEMPLATE'], target)
        target.chmod(0o755)
        opt = root / 'opt/python@3.13'
        if opt.is_symlink() and not opt.exists():
            opt.unlink()
        if not opt.exists():
            opt.symlink_to(pathlib.Path(os.environ['MOCK_FORMULA']), target_is_directory=True)
        libexec = pathlib.Path(os.environ['MOCK_FORMULA']) / 'libexec/bin'
        libexec.mkdir(parents=True, exist_ok=True)
        for name in ('python3', 'python'):
            path = libexec / name
            if not path.exists():
                path.symlink_to('../../bin/python3.13')
else:
    raise SystemExit(92)
''')
        self.env = {
            'HOME': str(self.home), 'SHELL': ZSH, 'TERM': 'xterm-256color',
            'PATH': f'{self.mockbin}:/usr/bin:/bin:/usr/sbin:/sbin',
            'TMPDIR': str(self.root) + '/', 'NO_COLOR': '1',
            'MOCK_LOG': str(self.log), 'MOCK_STATE': str(self.state),
            'MOCK_TEMPLATE': str(self.template), 'MOCK_FORMULA': str(self.formula),
            'MOCK_BREW_ROOT': str(self.brew_root), 'MOCK_BREW_BIN': str(self.brew_bin),
        }
        # Only public Homebrew helper boundaries are replaced. Runtime checks execute
        # the real probe body against a harmless Python shim and a real Cellar layout.
        self.prefix = '\nsource ' + shlex.quote(str(self.core)) + '\n' + r'''
jobs_brew_find() {
  print -r -- 'helper:find' >> "$MOCK_LOG"
  [[ "${MOCK_BREW_MISSING:-0}" != 1 ]] || return 1
  print -r -- "$MOCK_BREW_BIN"
}
jobs_brew_choose_installation() {
  print -r -- 'helper:choose' >> "$MOCK_LOG"
  typeset -g JOBS_HOMEBREW_INSTALL_MODE="${MOCK_INSTALL_MODE:-user}"
}
jobs_brew_install_system() {
  print -r -- 'helper:install-system' >> "$MOCK_LOG"
  [[ "${MOCK_BREW_INSTALL_FAIL:-0}" != 1 ]] || return 1
  typeset -g JOBS_HOMEBREW_BIN="$MOCK_BREW_BIN"
}
jobs_brew_install_user() {
  print -r -- 'helper:install-user' >> "$MOCK_LOG"
  [[ "${MOCK_BREW_INSTALL_FAIL:-0}" != 1 ]] || return 1
  typeset -g JOBS_HOMEBREW_BIN="$MOCK_BREW_BIN"
}
jobs_brew_activate() {
  print -r -- "helper:activate:${1:-existing}" >> "$MOCK_LOG"
  [[ "${MOCK_ACTIVATE_FAIL:-0}" != 1 ]] || return 1
  typeset -g JOBS_HOMEBREW_PREFIX="$MOCK_BREW_ROOT"
  export PATH="$MOCK_BREW_ROOT/bin:$PATH"
}

# Real xcode-select is never reached, including on fresh CI machines.
_jobs_python_require_clt_for_install() {
  print -r -- 'helper:clt' >> "$MOCK_LOG"
  [[ "${MOCK_CLT_MISSING:-0}" != 1 ]]
}
'''

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def write_executable(path, content):
        path.write_text(content, encoding='utf-8')
        path.chmod(0o755)

    def set_state(self, version='3.13.9', broken='', available=True):
        self.state.write_text(json.dumps(dict(version=version, broken=broken, available=available)), encoding='utf-8')

    def install_python(self):
        target = self.formula / 'bin' / 'python3.13'
        shutil.copyfile(self.template, target)
        target.chmod(0o755)
        libexec = self.formula / 'libexec/bin'
        libexec.mkdir(parents=True)
        for name in ('python3', 'python'):
            (libexec / name).symlink_to('../../bin/python3.13')

    def runtime(self, version='3.13.9', broken='', available=True):
        self.set_state(version, broken, available)
        if not available:
            for child in (self.formula / 'bin').iterdir():
                child.unlink()

    def venv(self, version='3.13.9', broken='', directory=None):
        directory = directory or self.root / '工具 带空格' / '.venv'
        (directory / 'bin').mkdir(parents=True)
        self.write_executable(directory / 'bin/python', self.template.read_text(encoding='utf-8'))
        (directory / 'bin/python3').symlink_to('python')
        (directory / 'pyvenv.cfg').write_text('home = mock\n', encoding='utf-8')
        (directory / '.mock-runtime.json').write_text(json.dumps(dict(version=version, broken=broken, venv=True)), encoding='utf-8')
        (directory / 'keep-me.txt').write_text('original user dependency and data', encoding='utf-8')
        return directory

    def calls(self):
        return self.log.read_text(encoding='utf-8').splitlines()

    def mutations(self):
        return [line for line in self.calls() if line.startswith(('brew:update', 'brew:install ', 'brew:upgrade ', 'brew:reinstall ', 'python:venv:', 'helper:install-'))]

    def run_pipe(self, code='', env=None, script=None):
        arguments = [ZSH, '-f', str(script)] if script else [ZSH, '-f', '-c', self.prefix + code]
        return subprocess.run(arguments, env=self.env | (env or {}),
                              input='', text=True, capture_output=True, timeout=10)

    def run_tty(self, code='', answer=b'\n', env=None, script=None):
        child_env = self.env | (env or {})
        pid, master = pty.fork()
        if pid == 0:
            arguments = [ZSH, '-f', str(script)] if script else [ZSH, '-f', '-c', self.prefix + code]
            os.execve(ZSH, arguments, child_env)
        output = bytearray()
        deadline = time.monotonic() + 12
        status = None
        try:
            if answer:
                os.write(master, answer)
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b''
                    output.extend(chunk)
                waited, wait_status = os.waitpid(pid, os.WNOHANG)
                if waited:
                    status = wait_status
                    break
            if status is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                raise AssertionError('PTY timed out: ' + output.decode(errors='replace'))
            while select.select([master], [], [], 0)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            return os.waitstatus_to_exitcode(status), output.decode(errors='replace')
        finally:
            os.close(master)

    def ensure(self, extra=''):
        return 'jobs_python_ensure 3.11 python@3.13 3.14 || exit $?; ' + extra

    def confirmed(self, extra=''):
        return 'jobs_python_mark_confirmed || exit $?; ' + self.ensure(extra)

    def standalone_entry(self, action):
        """孤立复制交付脚本，仅替换外部工具边界并运行实际内嵌自检。"""
        clone = self.root / '全新电脑 中文 🫡 独立拷贝'
        clone.mkdir()
        entry = clone / ENTRY.name
        source = ENTRY.read_text(encoding='utf-8').rsplit('main "$@"', 1)[0]
        source_line = '\nsource ' + shlex.quote(str(self.core)) + '\n'
        boundaries = self.prefix.split(source_line, 1)[1]
        entry.write_text(source + '\n' + boundaries + '\n' + action + '\n', encoding='utf-8')
        self.assertFalse((clone / 'HomebrewSupport').exists())
        self.assertFalse((clone.parent / 'HomebrewSupport').exists())
        return entry

    def test_isolated_script_checks_runtime_without_external_modules(self):
        entry = self.standalone_entry(
            'prepare_display_paths; jobs_python_mark_confirmed; check_environment; '
            'print -r -- STANDALONE_READY')
        code, output = self.run_tty(script=entry)
        self.assertEqual(code, 0, output)
        self.assertIn('STANDALONE_READY', output)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_isolated_script_runtime_failure_stops_without_business(self):
        entry = self.standalone_entry(
            'prepare_display_paths; jobs_python_mark_confirmed; check_environment; '
            'print -r -- BUSINESS')
        code, output = self.run_tty(script=entry, env={'MOCK_UPDATE_FAIL': '19'})
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS', output)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_isolated_script_cancellation_stops_without_any_mutation(self):
        entry = self.standalone_entry('prepare_display_paths; check_environment; print -r -- BUSINESS')
        code, output = self.run_tty(script=entry, answer=b' \n')
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.mutations(), [])

    def test_source_has_no_probes_or_writes(self):
        result = self.run_pipe('print -r -- SOURCE_READY')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SOURCE_READY', result.stdout)
        self.assertEqual(self.calls(), [])

    def test_healthy_readonly_runtime_works_without_tty(self):
        result = self.run_pipe(self.ensure('print -r -- "SELECTED:$JOBS_PYTHON_BIN"'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SELECTED:', result.stdout)
        self.assertEqual(self.mutations(), [])

    def test_sourcetree_healthy_runtime_is_readonly(self):
        result = self.run_pipe(self.ensure(), {'IS_SOURCETREE_RUNTIME': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_tty_without_confirmation_only_reads_healthy_runtime(self):
        code, output = self.run_tty(self.ensure())
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), [])

    def test_selected_runtime_and_path_are_exported_without_clobbering_venv(self):
        result = self.run_pipe('PYTHON_BIN=existing-venv; ' + self.ensure(
            'print -r -- "VENV:$PYTHON_BIN"; print -r -- "PATH_HEAD:${path[1]}"; /usr/bin/env'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('VENV:existing-venv', result.stdout)
        self.assertIn('JOBS_PYTHON_BIN=', result.stdout)
        self.assertIn('PATH_HEAD:', result.stdout)

    def test_path_python3_resolves_to_selected_brew_runtime(self):
        result = self.run_pipe(self.ensure(
            'print -r -- "PATH_PYTHON:$(command -v python3)"; '
            'python3 -c \'import sys; print("EXECUTED:" + sys.executable)\''))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PATH_PYTHON:' + str(self.opt / 'libexec/bin/python3'), result.stdout)
        self.assertIn('EXECUTED:' + str(self.formula / 'bin/python3.13'), result.stdout)

    def test_unversioned_python_formula_alias_uses_canonical_cellar(self):
        result = self.run_pipe('jobs_python_ensure 3.11 python 3.14 || exit $?; print -r -- "SELECTED:$JOBS_PYTHON_BIN"')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SELECTED:', result.stdout)
        self.assertEqual(self.mutations(), [])

    def test_confirmed_healthy_runtime_updates_brew_once_but_not_python(self):
        code, output = self.run_tty(self.confirmed(self.ensure()))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.calls().count('brew:update'), 1)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_update_failure_stops_before_runtime_mutation(self):
        self.runtime(version='3.9.6')
        code, output = self.run_tty(self.confirmed('print -r -- BUSINESS'), env={'MOCK_UPDATE_FAIL': '17'})
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS', output)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_failed_brew_update_is_not_cached_as_success(self):
        code, output = self.run_tty(
            'jobs_python_mark_confirmed; if jobs_python_ensure 3.11 python@3.13 3.14; then exit 98; fi; '
            'export MOCK_UPDATE_FAIL=0; ' + self.ensure(), env={'MOCK_UPDATE_FAIL': '17'})
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:update'])

    def test_confirm_prepare_enter_authorizes_update(self):
        code, output = self.run_tty('jobs_python_confirm_prepare || exit $?; ' + self.ensure())
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_confirm_prepare_does_not_prompt_twice_in_confirmed_process(self):
        code, output = self.run_tty(
            'jobs_python_confirm_prepare || exit $?; jobs_python_confirm_prepare || exit $?; ' + self.ensure())
        self.assertEqual(code, 0, output)
        self.assertEqual(output.count('➤ 按回车准备环境'), 1)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_confirm_prepare_nonempty_or_space_cancels_without_writes(self):
        for answer in (b'cancel\n', b' \n'):
            with self.subTest(answer=answer):
                code, output = self.run_tty('jobs_python_confirm_prepare || exit $?; ' + self.ensure(), answer)
                self.assertNotEqual(code, 0, output)
                self.assertEqual(self.mutations(), [])

    def test_confirm_prepare_eof_stops_without_writes(self):
        code, output = self.run_tty('jobs_python_confirm_prepare || exit $?; ' + self.ensure(), b'\x04')
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.mutations(), [])

    def test_confirm_prepare_non_tty_cannot_authorize_mutation(self):
        result = self.run_pipe('jobs_python_confirm_prepare || exit $?; ' + self.ensure())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_environment_cannot_fake_process_confirmation_or_updated_brew(self):
        self.runtime(version='3.9.6')
        result = self.run_pipe(self.ensure(), {
            '_JOBS_PYTHON_CONFIRMED_PROCESS': '1', '_JOBS_PYTHON_UPDATED_BREWS': '1',
            'JOBS_PYTHON_CONFIRMED': '1', 'JOBS_PYTHON_PREPARED': '1',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_fake_environment_updated_token_does_not_skip_real_update(self):
        code, output = self.run_tty(self.confirmed(), env={'_JOBS_PYTHON_UPDATED_BREWS': str(self.brew_bin)})
        self.assertEqual(code, 0, output)
        self.assertEqual(self.calls().count('brew:update'), 1)

    def test_even_exact_exported_process_token_cannot_authorize_writes(self):
        self.runtime(version='3.9.6')
        code, output = self.run_tty(
            'export _JOBS_PYTHON_CONFIRMED_PROCESS="$$:$((ZSH_SUBSHELL + 1))"; ' + self.ensure())
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.mutations(), [])

    def test_subshell_cannot_inherit_parent_write_authorization(self):
        self.runtime(version='3.9.6')
        code, output = self.run_tty(
            'jobs_python_mark_confirmed; ( ' + self.ensure() + ' )')
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.mutations(), [])

    def test_missing_python_non_tty_stops_without_write(self):
        self.runtime(available=False)
        result = self.run_pipe(self.ensure())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_low_python_non_tty_stops_without_write(self):
        self.runtime(version='3.9.6')
        result = self.run_pipe(self.ensure())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_missing_brew_non_tty_stops_before_choice_or_install(self):
        result = self.run_pipe(self.ensure(), {'MOCK_BREW_MISSING': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('helper:choose', self.calls())
        self.assertEqual(self.mutations(), [])

    def test_sourcetree_missing_runtime_never_installs(self):
        self.runtime(available=False)
        result = self.run_pipe(self.ensure(), {'IS_SOURCETREE_RUNTIME': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_missing_runtime_installs_formula_and_rechecks(self):
        self.runtime(available=False)
        code, output = self.run_tty(self.confirmed('print -r -- "READY:$JOBS_PYTHON_BIN"'))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:install python@3.13'])
        self.assertIn('READY:', output)

    def test_required_python_install_prompt_rejects_space_or_eof(self):
        self.runtime(available=False)
        for answer in (b' \n', b'\x04'):
            with self.subTest(answer=answer):
                self.log.write_text('', encoding='utf-8')
                code, output = self.run_tty(self.confirmed(), answer)
                self.assertNotEqual(code, 0, output)
                self.assertEqual(self.mutations(), ['brew:update'])

    def test_uninstalled_formula_prefix_may_print_missing_path_successfully(self):
        self.runtime(available=False)
        self.opt.unlink()
        code, output = self.run_tty(self.confirmed(), env={'MOCK_MISSING_PREFIX_RETURN': '1'})
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:install python@3.13'])

    def test_dangling_formula_opt_inside_its_cellar_is_repaired(self):
        self.opt.unlink()
        self.opt.symlink_to(self.cellar / 'python@3.13/missing-version', target_is_directory=True)
        code, output = self.run_tty(self.confirmed())
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:reinstall python@3.13'])

    def test_low_runtime_upgrades_formula_and_rechecks(self):
        self.runtime(version='3.9.6')
        code, output = self.run_tty(self.confirmed())
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:upgrade python@3.13'])

    def test_damaged_stdlib_reinstalls_only_once(self):
        self.runtime(broken='venv')
        code, output = self.run_tty(self.confirmed())
        self.assertEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:reinstall python@3.13'])

    def test_tomllib_is_checked_for_python_311_or_later(self):
        self.runtime(broken='tomllib')
        code, output = self.run_tty(self.confirmed())
        self.assertEqual(code, 0, output)
        self.assertIn('brew:reinstall python@3.13', self.mutations())

    def test_repair_failure_stops_business(self):
        self.runtime(version='3.9.6')
        code, output = self.run_tty(self.confirmed('print -r -- BUSINESS'), env={'MOCK_MUTATION_FAIL': '1'})
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS', output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:upgrade python@3.13'])

    def test_failed_post_repair_check_stops_without_retry_loop(self):
        self.runtime(broken='venv')
        code, output = self.run_tty(self.confirmed('print -r -- BUSINESS'), env={'MOCK_REPAIR_STILL_BROKEN': '1'})
        self.assertNotEqual(code, 0, output)
        self.assertNotIn('BUSINESS', output)
        self.assertEqual(self.mutations(), ['brew:update', 'brew:reinstall python@3.13'])

    def test_maximum_exclusive_rejects_newer_incompatible_runtime(self):
        self.runtime(version='3.14.0')
        result = self.run_pipe(self.ensure())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_confirmed_newer_incompatible_runtime_is_not_upgraded(self):
        self.runtime(version='3.14.0')
        code, output = self.run_tty(self.confirmed())
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_formula_escape_or_invalid_version_stops_without_writes(self):
        for arguments in ('broken python@3.13', '3.11 ../python', '3.11 python@3.13 3.10'):
            with self.subTest(arguments=arguments):
                result = self.run_pipe('jobs_python_ensure ' + arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.mutations(), [])

    def test_formula_opt_link_outside_cellar_is_rejected(self):
        foreign = self.root / 'foreign-python'
        (foreign / 'bin').mkdir(parents=True)
        self.write_executable(foreign / 'bin/python3.13', self.template.read_text(encoding='utf-8'))
        self.opt.unlink()
        self.opt.symlink_to(foreign, target_is_directory=True)
        result = self.run_pipe(self.ensure())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_python_executable_link_outside_formula_is_rejected(self):
        foreign = self.root / 'foreign-python'
        self.write_executable(foreign, self.template.read_text(encoding='utf-8'))
        (self.formula / 'bin/python3.13').unlink()
        (self.formula / 'bin/python3.13').symlink_to(foreign)
        result = self.run_pipe(self.ensure())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])

    def test_missing_brew_install_uses_existing_choice_module_and_updates(self):
        code, output = self.run_tty(self.confirmed(), env={'MOCK_BREW_MISSING': '1'})
        self.assertEqual(code, 0, output)
        self.assertIn('helper:choose', self.calls())
        self.assertEqual(self.mutations(), ['helper:install-user', 'brew:update'])

    def test_failed_brew_install_stops_without_update_or_python_install(self):
        code, output = self.run_tty(self.confirmed(), env={'MOCK_BREW_MISSING': '1', 'MOCK_BREW_INSTALL_FAIL': '1'})
        self.assertNotEqual(code, 0, output)
        self.assertEqual(self.mutations(), ['helper:install-user'])

    def test_unavailable_clt_stops_before_brew_installation(self):
        code, output = self.run_tty(self.confirmed(), env={'MOCK_BREW_MISSING': '1', 'MOCK_CLT_MISSING': '1'})
        self.assertNotEqual(code, 0, output)
        self.assertIn('helper:clt', self.calls())
        self.assertNotIn('helper:choose', self.calls())
        self.assertEqual(self.mutations(), [])

    def test_new_venv_uses_selected_runtime_and_supports_spaces(self):
        destination = self.root / '项目 中文' / '.venv'
        quoted = shlex.quote(str(destination))
        code, output = self.run_tty(self.confirmed(f'jobs_python_prepare_venv {quoted} 3.11 3.14 || exit $?; print -r -- VENV_READY'))
        self.assertEqual(code, 0, output)
        self.assertTrue((destination / 'bin/python').exists())
        self.assertIn('VENV_READY', output)
        self.assertEqual(len([item for item in self.calls() if item.startswith('python:venv:')]), 1)

    def test_healthy_venv_is_reused_without_mutation(self):
        destination = self.venv()
        before = (destination / 'keep-me.txt').read_bytes()
        result = self.run_pipe(self.ensure(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((destination / 'keep-me.txt').read_bytes(), before)
        self.assertEqual(self.mutations(), [])
        self.assertEqual(len(list(destination.parent.glob('.venv*'))), 1)

    def test_old_venv_is_fully_preserved_in_backup_before_recreation(self):
        destination = self.venv(version='3.9.6')
        code, output = self.run_tty(self.confirmed(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14 || exit $?'), b'\n')
        self.assertEqual(code, 0, output)
        backups = [path for path in destination.parent.iterdir() if path != destination and path.is_dir()]
        self.assertEqual(len(backups), 1, output)
        self.assertEqual((backups[0] / 'keep-me.txt').read_text(encoding='utf-8'), 'original user dependency and data')
        self.assertFalse((destination / 'keep-me.txt').exists())

    def test_damaged_venv_recreation_requires_its_own_enter(self):
        destination = self.venv(broken='venv')
        code, output = self.run_tty(self.confirmed(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14 || exit $?'), b'cancel\n')
        self.assertNotEqual(code, 0, output)
        self.assertTrue((destination / 'keep-me.txt').exists())
        self.assertEqual(len(list(destination.parent.iterdir())), 1)
        self.assertFalse(any(line.startswith('python:venv:') for line in self.calls()))

    def test_old_venv_space_and_eof_cancel_without_rename(self):
        destination = self.venv(version='3.9.6')
        for answer in (b' \n', b'\x04'):
            with self.subTest(answer=answer):
                code, output = self.run_tty(self.confirmed(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14 || exit $?'), answer)
                self.assertNotEqual(code, 0, output)
                self.assertTrue((destination / 'keep-me.txt').exists())
                self.assertEqual(len(list(destination.parent.iterdir())), 1)
                self.assertFalse(any(line.startswith('python:venv:') for line in self.calls()))

    def test_bad_venv_non_tty_is_never_renamed(self):
        destination = self.venv(version='3.9.6')
        result = self.run_pipe(self.ensure(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14'))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((destination / 'keep-me.txt').exists())
        self.assertEqual(self.mutations(), [])

    def test_new_venv_non_tty_is_not_created(self):
        destination = self.root / 'project' / '.venv'
        result = self.run_pipe(self.ensure(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(destination.exists())
        self.assertEqual(self.mutations(), [])

    def test_inherited_runtime_variable_cannot_create_venv(self):
        destination = self.root / 'project' / '.venv'
        code, output = self.run_tty(
            'jobs_python_mark_confirmed; '
            f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14 || exit $?',
            env={'JOBS_PYTHON_BIN': str(self.formula / 'bin/python3.13')})
        self.assertNotEqual(code, 0, output)
        self.assertFalse(destination.exists())
        self.assertEqual(self.mutations(), [])

    def test_selected_runtime_is_rechecked_against_venv_version_bounds(self):
        destination = self.root / 'project' / '.venv'
        code, output = self.run_tty(self.confirmed(
            f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.14 3.15 || exit $?'))
        self.assertNotEqual(code, 0, output)
        self.assertFalse(destination.exists())
        self.assertEqual(self.mutations(), ['brew:update'])

    def test_venv_rejects_symlink_root_home_and_source_directory(self):
        actual = self.venv()
        link = self.root / 'venv-link'
        link.symlink_to(actual, target_is_directory=True)
        for destination in (link, Path('/'), self.home, self.root):
            with self.subTest(destination=destination):
                result = self.run_pipe(self.ensure(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14'))
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue((actual / 'keep-me.txt').exists())
                self.assertEqual(self.mutations(), [])

    def test_ordinary_source_directory_is_not_renamed_after_confirmation(self):
        source = self.root / 'project-source'
        source.mkdir()
        (source / 'app.py').write_text('print("user source")\n', encoding='utf-8')
        code, output = self.run_tty(self.confirmed(
            f'jobs_python_prepare_venv {shlex.quote(str(source))} 3.11 3.14 || exit $?'))
        self.assertNotEqual(code, 0, output)
        self.assertTrue((source / 'app.py').exists())
        self.assertFalse(any(self.root.glob('project-source.backup.*')))
        self.assertFalse(any(line.startswith('python:venv:') for line in self.calls()))

    def test_symbolic_link_in_venv_parent_is_rejected(self):
        actual = self.root / 'real-project'
        actual.mkdir()
        link = self.root / 'linked-project'
        link.symlink_to(actual, target_is_directory=True)
        code, output = self.run_tty(self.confirmed(
            f'jobs_python_prepare_venv {shlex.quote(str(link / ".venv"))} 3.11 3.14 || exit $?'))
        self.assertNotEqual(code, 0, output)
        self.assertFalse((actual / '.venv').exists())

    def test_truncated_old_dotvenv_can_be_preserved_and_recreated(self):
        destination = self.root / 'project' / '.venv'
        destination.mkdir(parents=True)
        (destination / 'leftover.data').write_text('keep old incomplete environment', encoding='utf-8')
        code, output = self.run_tty(self.confirmed(
            f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14 || exit $?'))
        self.assertEqual(code, 0, output)
        backups = list(destination.parent.glob('.venv.backup.*'))
        self.assertEqual(len(backups), 1, output)
        self.assertEqual((backups[0] / 'leftover.data').read_text(encoding='utf-8'),
                         'keep old incomplete environment')
        self.assertTrue((destination / 'bin/python').exists())

    def test_venv_creation_failure_keeps_complete_backup(self):
        destination = self.venv(version='3.9.6')
        code, output = self.run_tty(self.confirmed(f'jobs_python_prepare_venv {shlex.quote(str(destination))} 3.11 3.14 || exit $?'), b'\n', {'MOCK_VENV_FAIL': '1'})
        self.assertNotEqual(code, 0, output)
        backups = [path for path in destination.parent.iterdir() if path != destination and path.is_dir()]
        self.assertEqual(len(backups), 1, output)
        self.assertEqual((backups[0] / 'keep-me.txt').read_text(encoding='utf-8'), 'original user dependency and data')


if __name__ == '__main__':
    unittest.main(verbosity=2)
