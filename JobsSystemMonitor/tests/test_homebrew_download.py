#!/usr/bin/env python3
"""Homebrew 官方下载、重试和安装门禁回归；全部网络与安装命令均使用隔离替身。"""
import os
from pathlib import Path
import unittest

import test_embedded_homebrew as _brew_fixture


RAW_URL = 'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh'
API_URL = 'https://api.github.com/repos/Homebrew/install/contents/install.sh?ref=HEAD'
RELEASE_URL = 'https://api.github.com/repos/Homebrew/brew/releases/latest'


@unittest.skipUnless(
    Path(_brew_fixture.ZSH).exists() and _brew_fixture.pty and os.name == 'posix',
    'Requires zsh and POSIX PTY.',
)
class HomebrewDownloadTests(unittest.TestCase):
    # 只复用夹具与执行工具，避免继承 TestCase 后重复发现已有用例。
    _write_executable = staticmethod(_brew_fixture.BrewChoiceTests._write_executable)
    tearDown = _brew_fixture.BrewChoiceTests.tearDown
    run_pipe = _brew_fixture.BrewChoiceTests.run_pipe
    run_tty = _brew_fixture.BrewChoiceTests.run_tty
    calls = _brew_fixture.BrewChoiceTests.calls
    install_existing = _brew_fixture.BrewChoiceTests.install_existing

    def setUp(self):
        _brew_fixture.BrewChoiceTests.setUp(self)
        self.destination = self.root / 'downloaded installer.sh'
        self.env['LOG_FILE'] = str(self.root / 'build.log')
        self._write_executable(self.mockbin / 'sleep', r'''#!/bin/zsh
print -r -- "sleep:$*" >> "$MOCK_LOG"
''')
        self._write_executable(self.mockbin / 'curl', r'''#!/bin/zsh
print -r -- "curl-args:$*" >> "$MOCK_LOG"
destination=''
source_url=''
while (( $# )); do
  case "$1" in
    -o) destination="$2"; shift 2 ;;
    https://*) source_url="$1"; shift ;;
    *) shift ;;
  esac
done
case "$source_url" in
  */install/HEAD/install.sh)
    kind=raw
    codes_string="${MOCK_RAW_CODES:-0}"
    http_string="${MOCK_RAW_HTTP:-200}"
    payload="${MOCK_RAW_BODY:-$MOCK_INSTALLER}"
    ;;
  */install/contents/install.sh\?ref=HEAD)
    kind=api
    codes_string="${MOCK_API_CODES:-0}"
    http_string="${MOCK_API_HTTP:-200}"
    payload="${MOCK_API_BODY:-$MOCK_INSTALLER}"
    ;;
  */releases/latest)
    kind=release
    codes_string="${MOCK_RELEASE_CODES:-0}"
    http_string="${MOCK_RELEASE_HTTP:-200}"
    payload=''
    ;;
  *) print -u2 -r -- "Unexpected URL: $source_url"; exit 97 ;;
esac
counter_file="$MOCK_ROOT/curl-$kind.count"
index=0
[[ ! -f "$counter_file" ]] || index="$(< "$counter_file")"
(( index += 1 ))
print -r -- "$index" > "$counter_file"
codes=(${=codes_string})
http_codes=(${=http_string})
result="${codes[$index]:-${codes[-1]}}"
http_code="${http_codes[$index]:-${http_codes[-1]}}"
previous=absent
[[ ! -e "$destination" ]] || previous=present
if [[ -f "$destination" && "$(< "$destination")" == PARTIAL_DOWNLOAD ]]; then
  previous=partial
fi
print -r -- "curl:$kind:$index:previous=$previous" >> "$MOCK_LOG"
if (( result != 0 )); then
  print -r -- PARTIAL_DOWNLOAD > "$destination"
  print -u2 -r -- "curl: ($result) fake failure for $kind"
elif [[ "$kind" == release ]]; then
  print -r -- '{"tag_name":"7.0.9"}' > "$destination"
else
  cp "$payload" "$destination" || exit 98
fi
printf '%s' "$http_code"
exit "$result"
''')

    def download(self, env=None, urls=(RAW_URL,)):
        arguments = ' '.join(repr(url) for url in urls)
        return self.run_pipe(
            f'jobs_brew_download_file {str(self.destination)!r} 测试下载 {arguments}', env,
        )

    def reset_calls(self):
        self.log.write_text('')
        for counter in self.root.glob('curl-*.count'):
            counter.unlink()
        Path(self.env['LOG_FILE']).unlink(missing_ok=True)

    def curl_calls(self, kind):
        return [line for line in self.calls().splitlines() if line.startswith(f'curl:{kind}:')]

    def assert_no_installation(self):
        self.assertNotIn('installer:', self.calls())
        self.assertNotIn('SUDO_TRAP', self.calls())
        self.assertNotIn('git:', self.calls())
        self.assertFalse((self.home / '.local/homebrew').exists())
        self.assertFalse((self.home / '.zprofile').exists())
        self.assertFalse((self.root / 'system').exists())
        self.assertEqual(list(self.root.glob('jobs-homebrew-install.*')), [])

    def test_transient_curl_errors_retry_three_times_and_preserve_exit_code(self):
        for curl_code in (5, 6, 7, 18, 28, 35, 52, 55, 56):
            with self.subTest(curl_code=curl_code):
                self.reset_calls()
                result = self.download({'MOCK_RAW_CODES': str(curl_code), 'MOCK_RAW_HTTP': '000'})
                self.assertEqual(result.returncode, curl_code, result.stdout + result.stderr)
                self.assertEqual(len(self.curl_calls('raw')), 3)
                self.assertEqual(self.calls().count('sleep:1\n'), 2)
                self.assertNotIn('previous=partial', self.calls())
                self.assertFalse(self.destination.exists())
                self.assertIn(f'curl: ({curl_code})', Path(self.env['LOG_FILE']).read_text())
                self.assert_no_installation()

    def test_retryable_http_statuses_retry_three_times(self):
        for http_code in (408, 429, 500, 502, 503, 599):
            with self.subTest(http_code=http_code):
                self.reset_calls()
                result = self.download({'MOCK_RAW_CODES': '22', 'MOCK_RAW_HTTP': str(http_code)})
                self.assertEqual(result.returncode, 22, result.stdout + result.stderr)
                self.assertEqual(len(self.curl_calls('raw')), 3)
                self.assertEqual(self.calls().count('sleep:1\n'), 2)
                self.assertFalse(self.destination.exists())

    def test_nonretryable_http_statuses_stop_after_one_attempt(self):
        for http_code in (400, 401, 403, 404):
            with self.subTest(http_code=http_code):
                self.reset_calls()
                result = self.download({'MOCK_RAW_CODES': '22', 'MOCK_RAW_HTTP': str(http_code)})
                self.assertEqual(result.returncode, 22, result.stdout + result.stderr)
                self.assertEqual(len(self.curl_calls('raw')), 1)
                self.assertNotIn('sleep:', self.calls())
                self.assertFalse(self.destination.exists())

    def test_certificate_failure_is_not_retried_but_can_use_next_official_url(self):
        result = self.download(
            {'MOCK_RAW_CODES': '60', 'MOCK_API_CODES': '60'}, urls=(RAW_URL, API_URL),
        )
        self.assertEqual(result.returncode, 60, result.stdout + result.stderr)
        self.assertEqual(len(self.curl_calls('raw')), 1)
        self.assertEqual(len(self.curl_calls('api')), 1)
        self.assertNotIn('sleep:', self.calls())
        self.assertFalse(self.destination.exists())
        self.assert_no_installation()

    def test_success_after_retry_replaces_partial_file_and_limits_curl_time(self):
        result = self.download({'MOCK_RAW_CODES': '35 0', 'MOCK_RAW_HTTP': '000 200'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), self.installer.read_bytes())
        self.assertEqual(len(self.curl_calls('raw')), 2)
        self.assertIn('curl:raw:2:previous=absent', self.calls())
        self.assertNotIn('curl:api:', self.calls())
        arguments = [line for line in self.calls().splitlines() if line.startswith('curl-args:')]
        self.assertEqual(len(arguments), 2)
        for line in arguments:
            self.assertTrue(line.startswith('curl-args:-q -fsSL '), line)
            self.assertIn('--proto =https --proto-redir =https', line)
            self.assertIn('--connect-timeout 10 --max-time 30', line)
            self.assertIn('--write-out %{http_code}', line)
            self.assertNotIn('--insecure', line)
            self.assertNotIn('--retry', line)

    def test_raw_failure_uses_official_api_then_executes_installer_once(self):
        code, output = self.run_tty(
            'jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'YES\n',
            {'MOCK_RAW_CODES': '35', 'MOCK_RAW_HTTP': '000'},
        )
        self.assertEqual(code, 0, output)
        self.assertIn('BUSINESS_REACHED', output)
        self.assertEqual(len(self.curl_calls('raw')), 3)
        self.assertEqual(len(self.curl_calls('api')), 1)
        self.assertEqual(self.calls().count('installer:'), 1)
        self.assertLess(self.calls().index('curl:raw:3:'), self.calls().index('curl:api:1:'))
        arguments = [line for line in self.calls().splitlines() if line.startswith('curl-args:')]
        for line in arguments[:3]:
            self.assertIn(RAW_URL, line)
            self.assertNotIn('Accept:', line)
        self.assertIn(API_URL, arguments[3])
        self.assertIn('-H Accept: application/vnd.github.raw+json', arguments[3])
        self.assertNotIn('git:', self.calls())
        self.assertNotIn('SUDO_TRAP', self.calls())
        self.assertFalse((self.home / '.local/homebrew').exists())
        self.assertEqual(list(self.root.glob('jobs-homebrew-install.*')), [])

    def test_all_download_failures_preserve_curl_code_and_clean_temporary_file(self):
        result = self.run_pipe(
            'jobs_brew_install_system',
            {'MOCK_RAW_CODES': '35', 'MOCK_API_CODES': '35',
             'MOCK_RAW_HTTP': '000', 'MOCK_API_HTTP': '000'},
        )
        self.assertEqual(result.returncode, 35, result.stdout + result.stderr)
        self.assertEqual(len(self.curl_calls('raw')), 3)
        self.assertEqual(len(self.curl_calls('api')), 3)
        self.assertIn('系统目录安装器下载失败（curl 退出码 35）', result.stderr)
        self.assert_no_installation()

    def test_all_download_failures_stop_outer_business_without_user_fallback(self):
        code, output = self.run_tty(
            'jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'YES\n',
            {'MOCK_RAW_CODES': '35', 'MOCK_API_CODES': '35'},
        )
        self.assertEqual(code, 1, output)
        self.assertIn('curl 退出码 35', output)
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assert_no_installation()

    def test_invalid_api_bodies_never_execute_and_clean_temporary_file(self):
        payloads = {
            'json': '{"message":"API rate limit exceeded"}\n',
            'html': '<html><body>Service unavailable</body></html>\n',
            'empty': '',
            'shebang': '#!/bin/sh\nprintf "SHOULD_NOT_RUN\\n" >> "$MOCK_LOG"\n',
            'syntax': '#!/bin/bash\nprintf "SHOULD_NOT_RUN\\n" >> "$MOCK_LOG"\nif\n',
        }
        for name, payload in payloads.items():
            with self.subTest(payload=name):
                self.reset_calls()
                body = self.root / f'{name}.response'
                body.write_text(payload)
                code, output = self.run_tty(
                    'jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'YES\n',
                    {'MOCK_RAW_CODES': '60', 'MOCK_API_BODY': str(body)},
                )
                self.assertEqual(code, 1, output)
                self.assertEqual(len(self.curl_calls('raw')), 1)
                self.assertEqual(len(self.curl_calls('api')), 1)
                self.assertIn('内容校验失败', output)
                self.assertNotIn('BUSINESS_REACHED', output)
                self.assertNotIn('SHOULD_NOT_RUN', self.calls())
                self.assert_no_installation()

    def test_invalid_successful_raw_response_stops_without_api_or_execution(self):
        body = self.root / 'raw-invalid.response'
        body.write_text('#!/bin/bash\nprintf "SHOULD_NOT_RUN\\n" >> "$MOCK_LOG"\nif\n')
        result = self.run_pipe('jobs_brew_install_system', {'MOCK_RAW_BODY': str(body)})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(self.curl_calls('raw')), 1)
        self.assertEqual(len(self.curl_calls('api')), 0)
        self.assertNotIn('SHOULD_NOT_RUN', self.calls())
        self.assert_no_installation()

    def test_installer_failure_is_not_retried_or_confused_with_download_failure(self):
        code, output = self.run_tty(
            'jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'YES\n',
            {'MOCK_INSTALL_FAIL': '1'},
        )
        self.assertEqual(code, 1, output)
        self.assertEqual(len(self.curl_calls('raw')), 1)
        self.assertEqual(len(self.curl_calls('api')), 0)
        self.assertEqual(self.calls().count('installer:'), 1)
        self.assertIn('系统目录安装失败（退出码 23）', output)
        self.assertNotIn('下载失败', output)
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertNotIn('git:', self.calls())
        self.assertFalse((self.home / '.local/homebrew').exists())
        self.assertFalse((self.home / '.zprofile').exists())
        self.assertEqual(list(self.root.glob('jobs-homebrew-install.*')), [])

    def test_user_release_failure_uses_same_retry_limit_without_fallback(self):
        code, output = self.run_tty(
            'jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'\n',
            {'MOCK_RELEASE_CODES': '35', 'MOCK_RELEASE_HTTP': '000'},
        )
        self.assertEqual(code, 1, output)
        self.assertEqual(len(self.curl_calls('release')), 3)
        self.assertNotIn('curl:raw:', self.calls())
        self.assertNotIn('curl:api:', self.calls())
        self.assertNotIn(' clone ', self.calls())
        self.assertNotIn('installer:', self.calls())
        self.assertNotIn('SUDO_TRAP', self.calls())
        self.assertNotIn('BUSINESS_REACHED', output)
        self.assertFalse((self.home / '.local/homebrew').exists())
        self.assertFalse((self.home / '.zprofile').exists())
        self.assertEqual(list((self.home / '.local').glob('.jobs-homebrew.*')), [])

    def test_user_release_can_retry_then_install_without_sudo(self):
        code, output = self.run_tty(
            'jobs_brew_install_or_exit; print -r -- BUSINESS_REACHED', b'\n',
            {'MOCK_RELEASE_CODES': '28 0', 'MOCK_RELEASE_HTTP': '000 200'},
        )
        self.assertEqual(code, 0, output)
        self.assertIn('BUSINESS_REACHED', output)
        self.assertEqual(len(self.curl_calls('release')), 2)
        self.assertIn(RELEASE_URL, self.calls())
        self.assertNotIn('Accept:', self.calls())
        self.assertNotIn('curl:raw:', self.calls())
        self.assertNotIn('curl:api:', self.calls())
        self.assertIn('git:NO_SUDO=1:', self.calls())
        self.assertIn('brew:config:NO_SUDO=1', self.calls())
        self.assertNotIn('installer:', self.calls())
        self.assertNotIn('SUDO_TRAP', self.calls())
        self.assertEqual(list((self.home / '.local').glob('.jobs-homebrew.*')), [])

    def test_signal_exit_codes_stop_without_retry_or_next_url(self):
        for curl_code in (130, 143):
            with self.subTest(curl_code=curl_code):
                self.reset_calls()
                result = self.download({'MOCK_RAW_CODES': str(curl_code)}, urls=(RAW_URL, API_URL))
                self.assertEqual(result.returncode, curl_code, result.stdout + result.stderr)
                self.assertEqual(len(self.curl_calls('raw')), 1)
                self.assertEqual(len(self.curl_calls('api')), 0)
                self.assertNotIn('sleep:', self.calls())
                self.assertFalse(self.destination.exists())
                self.assert_no_installation()

    def test_noninteractive_and_dry_run_keep_installation_gates(self):
        for env in ({}, {'IS_SOURCETREE_RUNTIME': '1'}, {'DRY_RUN': '1'}):
            with self.subTest(env=env):
                self.reset_calls()
                result = self.run_pipe('jobs_brew_install_or_exit; print BUSINESS_REACHED', env)
                if env.get('DRY_RUN') == '1':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('BUSINESS_REACHED', result.stdout)
                self.assertNotIn('curl:', self.calls())
                self.assert_no_installation()

    def test_existing_healthy_brew_skips_all_downloads(self):
        existing = self.install_existing()
        result = self.run_pipe(
            'jobs_brew_install_or_exit; print BUSINESS_REACHED',
            {'JOBS_HOMEBREW_BIN': str(existing / 'bin/brew')},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('BUSINESS_REACHED', result.stdout)
        self.assertNotIn('curl:', self.calls())
        self.assert_no_installation()


if __name__ == '__main__':
    unittest.main()
