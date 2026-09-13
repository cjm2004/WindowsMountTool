"""云盘挂载向导 · 配置程序

基于 Alist + rclone + WinFsp 把多个网盘挂载为本地盘符。
- 首次配置：鱼骨式分步向导
- 已配置：直接进入控制台主页面（左侧分区导航）
- 磨砂玻璃 + 暗/亮主题（跟随系统，可手动切换）
- 内嵌 pywebview 浏览 Alist 后台
"""
import ctypes
import json
import os
import queue
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ui_theme
from ui_theme import Theme

# pywebview 内嵌浏览器（可选）
try:
    import webview
    HAS_WEBVIEW = True
except Exception:
    webview = None
    HAS_WEBVIEW = False

APP_TITLE = '云盘挂载向导'
APP_VERSION = '1.0.0'
PROJECT_AUTHOR = '陈嘉明'
PROJECT_GITHUB = 'https://github.com/cjm2004/WindowsMountTool'

TASK_MOUNT = 'CloudDriveMount'
TASK_HEALTH = 'CloudDriveHealth'
ALIST_PORT = 5244
ALIST_URL = f'http://127.0.0.1:{ALIST_PORT}'
ALIST_WEBDAV = f'{ALIST_URL}/dav'

MOUNT_LETTERS = list('DEFGHIJKLMNOPQRSTUVWXYZ')
LOCK_NAME = 'cloud-mount-wizard.lock'
HEALTH_INTERVAL = 180
ALIST_READY_TIMEOUT = 40
LOG_TAIL = 400


def frozen():
    return bool(getattr(sys, 'frozen', False))


def bundled_root():
    if frozen():
        return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'source'
    return Path(__file__).resolve().parent


def runtime_root():
    if not frozen():
        return bundled_root()
    preferred = Path(sys.executable).resolve().parent / 'runtime'
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
        return preferred
    except OSError:
        fallback = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CloudDriveWizard'
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def prepare_runtime():
    root = runtime_root()
    if frozen():
        source = bundled_root()
        for name in ('scripts', 'docs', 'README.txt'):
            dst = root / name
            src = source / name
            try:
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                    for item in src.rglob('*'):
                        target = dst / item.relative_to(src)
                        if item.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, target)
                elif src.is_file():
                    shutil.copy2(src, dst)
            except OSError:
                continue
        for name in ('tools', 'config'):
            dst = root / name
            src = source / name
            if src.is_dir() and not dst.exists():
                shutil.copytree(src, dst)
    for name in ('config', 'data', 'logs'):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def hidden_kwargs():
    kwargs = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs['startupinfo'] = startup
    return kwargs


def clean_env():
    """代理软件关闭后系统代理变量会指向失效端口，rclone/Alist 需要直连。"""
    env = os.environ.copy()
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        env.pop(key, None)
    env.setdefault('NO_PROXY', '*')
    env.setdefault('no_proxy', '*')
    return env


def drive_ready(letter):
    """真实检测盘符是否可访问（不是仅看 GetLogicalDrives）"""
    s = str(letter).strip().rstrip(':').upper()
    if len(s) != 1 or not s.isalpha():
        return False
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return bool(mask & (1 << (ord(s) - ord('A'))))
    except Exception:
        pass
    drive = f'{s}:\\'
    try:
        return os.path.isdir(drive)
    except OSError:
        return False


def drive_probe(letter):
    s = str(letter).strip().rstrip(':').upper()
    if len(s) != 1:
        return False, '盘符格式不正确'
    drive = f'{s}:\\'
    try:
        if os.path.exists(drive):
            return True, '已被本地磁盘或其他程序占用'
        return False, ''
    except OSError as exc:
        return False, str(exc)


def refresh_explorer_drive(letter, added):
    """Notify Explorer after WinFsp changes a drive letter in this logon session."""
    s = str(letter).strip().rstrip(':').upper()
    if len(s) != 1:
        return
    drive = f'{s}:'
    try:
        ctypes.windll.shell32.SHChangeNotify(0x00008000, 0x0000, None, None)
        if added:
            subprocess.run(['cmd.exe', '/c', 'subst', drive, drive], capture_output=True, **hidden_kwargs())
        else:
            subprocess.run(['cmd.exe', '/c', 'subst', '/d', drive], capture_output=True, **hidden_kwargs())
    except OSError:
        pass


def clear_legacy_network_locations():
    """清理历史遗留的 WebDAV 网络位置，避免占用盘符。"""
    try:
        result = subprocess.run(
            ['reg.exe', 'query', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Map Network Drive MRU'],
            capture_output=True, text=True, **hidden_kwargs()
        )
        if result.returncode == 0:
            subprocess.run(
                ['reg.exe', 'delete', 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Map Network Drive MRU', '/f'],
                capture_output=True, **hidden_kwargs()
            )
    except OSError:
        pass


def volume_name(item):
    return f'{item.drive}_{item.remote_id}'[:32] or 'CloudMount'


def mount_operation_lock(root=None):
    """返回跨进程挂载锁路径。"""
    base = Path(root) if root is not None else runtime_root()
    lock_path = base / 'logs' / LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return lock_path


@contextmanager
def acquire_mount_lock(root, timeout=45):
    """使用 Windows 文件锁串行化 UI、计划任务和健康检查的挂载操作。"""
    if os.name != 'nt':
        yield
        return
    import msvcrt
    handle = mount_operation_lock(root).open('a+b')
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b'\0')
        handle.flush()
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while time.monotonic() < deadline:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
                break
            except OSError:
                time.sleep(0.2)
        if not acquired:
            raise RuntimeError('已有其他挂载操作正在执行，请稍后再试')
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        handle.close()


def process_alive(pid):
    if not pid:
        return False
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return False


def process_command_line(pid):
    try:
        import ctypes.wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not h:
            return ''
        try:
            PROCESS_BASIC_INFORMATION = 0
            buf = (ctypes.c_char * 1024)()
            pbi = ctypes.addressof(buf)
            returnlength = ctypes.c_ulong()
            # Best-effort: return '' if it fails
            return ''
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return ''


def managed_mount(root, item):
    """根据 item.drive + item.remote 标识符返回 rclone 进程 PID 记录路径。"""
    pids_path = root / 'logs' / 'rclone_pids.json'
    return pids_path


def port_open(port=ALIST_PORT):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.8)
    try:
        s.connect(('127.0.0.1', port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def winfsp_installed():
    import winreg
    for sub in (r'SOFTWARE\WinFsp', r'SOFTWARE\WOW6432Node\WinFsp'):
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub)
            return True
        except OSError:
            continue
    return False


def available_letters():
    taken = set()
    for letter in string.ascii_uppercase:
        drive = f'{letter}:\\'
        try:
            if Path(drive).exists():
                taken.add(letter)
        except OSError:
            continue
    return [letter for letter in MOUNT_LETTERS if letter not in taken]


def load_settings(root):
    settings_path = root / 'config' / 'settings.json'
    if not settings_path.exists():
        return {'items': [], 'alist_user': 'admin', 'alist_pass': '', 'use_https': False, 'webdav_path': '/dav'}
    try:
        data = json.loads(settings_path.read_text(encoding='utf-8'))
        if 'items' not in data:
            data['items'] = []
        return data
    except (OSError, ValueError):
        return {'items': [], 'alist_user': 'admin', 'alist_pass': '', 'use_https': False, 'webdav_path': '/dav'}


def save_settings(root, settings):
    settings_path = root / 'config' / 'settings.json'
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = settings_path.with_suffix('.json.tmp')
    payload = json.dumps(settings, ensure_ascii=False, indent=2) + '\n'
    temp_path.write_text(payload, encoding='utf-8')
    os.replace(temp_path, settings_path)


def is_configured(root):
    """是否已完成首次配置：有 alist_pass 或已有挂载方案。"""
    settings = load_settings(root)
    return bool(settings.get('alist_pass') or settings.get('items'))


def decode_command_output(data, command=None):
    if not data:
        data = b''
    if isinstance(data, str):
        return data.strip()
    is_schtasks = bool(command) and str(command[0]).lower().endswith(('schtasks.exe', 'schtasks'))
    encodings = ('gbk', 'cp936', 'utf-8', 'mbcs') if is_schtasks else ('utf-8', 'gbk', 'mbcs')
    for encoding in encodings:
        try:
            return data.decode(encoding).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace').strip()


def run_capture(command, root, timeout=60, env=None):
    completed = subprocess.run(
        command, cwd=str(root), capture_output=True, timeout=timeout, env=env, **hidden_kwargs()
    )
    stdout_part = completed.stdout or b''
    stderr_part = completed.stderr or b''
    raw_output = decode_command_output(stdout_part + stderr_part, command)
    if completed.returncode:
        raise RuntimeError(f'命令返回码 {completed.returncode}\n{raw_output[-1800:]}')
    return raw_output


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def task_actions(wizard_exe):
    return [
        ['schtasks.exe', '/Create', '/RU', 'SYSTEM', '/RL', 'HIGHEST', '/F',
         '/TN', TASK_MOUNT, '/SC', 'ONLOGON', '/TR', f'"{wizard_exe}" --startup'],
        ['schtasks.exe', '/Create', '/RU', 'SYSTEM', '/RL', 'HIGHEST', '/F',
         '/TN', TASK_HEALTH, '/SC', 'MINUTE', '/MO', '3', '/TR', f'"{wizard_exe}" --health'],
    ]


def current_task_user():
    try:
        result = subprocess.run(['whoami.exe', '/user'], capture_output=True, text=True, **hidden_kwargs())
        for line in result.stdout.splitlines():
            if 'User Name' in line:
                return line.split('User Name')[-1].strip()
    except OSError:
        pass
    return ''


def install_scheduled_tasks(root):
    """安装登录自启 + 每 3 分钟健康检查的计划任务。需 admin。"""
    if not is_admin():
        raise RuntimeError('管理员权限未生效')
    wizard_exe = sys.executable if frozen() else (Path(__file__).resolve().parent / 'app.pyw')
    wizard_exe_str = str(wizard_exe)
    for command in task_actions(wizard_exe_str):
        result = subprocess.run(command, capture_output=True, **hidden_kwargs())
        if result.returncode != 0:
            raise RuntimeError(f'计划任务创建失败: {result.stderr.decode("utf-8", errors="replace")}')


def request_task_install(root):
    """通过 UAC 提权来调用 install_scheduled_tasks。"""
    wizard_exe = sys.executable if frozen() else (Path(__file__).resolve().parent / 'app.pyw')
    if getattr(sys, 'frozen', False):
        result = subprocess.run(
            [str(wizard_exe), '--install-tasks', '--result', str(root / 'logs' / 'task_install.json')],
            capture_output=True, **hidden_kwargs()
        )
    else:
        install_scheduled_tasks(root)
        return
    result_path = root / 'logs' / 'task_install.json'
    if not result_path.exists():
        raise RuntimeError('无法请求管理员权限：计划任务安装结果未生成。')
    try:
        data = json.loads(result_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'读取任务结果失败: {exc}')
    result_path.unlink(missing_ok=True)
    if not data.get('ok'):
        raise RuntimeError(data.get('error') or '管理员进程未返回具体错误')


def obscure(root, password):
    rclone = root / 'tools' / 'rclone.exe'
    if not rclone.exists():
        raise FileNotFoundError(f'缺少工具：{rclone}')
    output = run_capture([str(rclone), 'obscure', password], root, env=clean_env())
    value = output.splitlines()[-1].strip() if output else ''
    if not value:
        raise RuntimeError('rclone 未返回加密密码串')
    return value


def webdav_url(item, settings=None):
    """生成 WebDAV 端点：直连 WebDAV 使用完整地址，Alist/OpenList 使用其 DAV 路径。"""
    url = str(item.url if isinstance(item, Item) else item.get('url', '')).rstrip('/')
    item_type = str(item.type if isinstance(item, Item) else item.get('type', 'WebDAV'))
    path = str(item.path if isinstance(item, Item) else item.get('path', '')).strip().lstrip('/')
    if item_type != 'WebDAV':
        dav_path = str((settings or {}).get('webdav_path', '/dav')).strip()
        if dav_path:
            url += '/' + dav_path.strip('/')
    if path:
        url += '/' + path
    return url


def write_rclone_config(root, settings):
    config_dir = root / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)
    conf_path = config_dir / 'rclone.conf'
    lines = []
    for item in settings.get('items', []):
        if not item.get('enabled', True):
            continue
        remote = f'cloud_{re.sub(r"[^a-zA-Z0-9]", "", item.get("id", ""))}'
        remote_name = remote + ':'
        url = item.get('url', '').rstrip('/')
        if not url:
            continue
        if settings.get('use_https', False) and url.startswith('http://'):
            item = dict(item)
            item['url'] = 'https://' + url[len('http://'):]
        user = item.get('user', 'admin')
        passwd = item.get('pass', '')
        lines.append(f'[{remote}]')
        lines.append('type = webdav')
        lines.append(f'url = {webdav_url(item, settings)}')
        lines.append('vendor = other')
        lines.append(f'user = {user}')
        lines.append(f'pass = {passwd}')
        lines.append('')
    content = '\n'.join(lines).rstrip() + '\n'
    # 必须无 BOM 写入，否则 rclone 解析不出 section
    from pathlib import Path as _P
    _P(conf_path).write_bytes(content.encode('utf-8'))


def start_alist(root):
    if port_open():
        return
    alist = root / 'tools' / 'alist.exe'
    if not alist.exists():
        alist = bundled_root() / 'tools' / 'alist.exe'
    if not alist.exists():
        raise FileNotFoundError(f'缺少工具：{alist}')
    subprocess.Popen(
        [str(alist), 'server'],
        cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env(),
        **hidden_kwargs()
    )
    for _ in range(ALIST_READY_TIMEOUT):
        if port_open():
            return
        time.sleep(1)
    raise RuntimeError('Alist 启动后 40 秒内未就绪')


def stop_alist():
    try:
        subprocess.run(['taskkill.exe', '/IM', 'alist.exe', '/F', '/T'], capture_output=True, **hidden_kwargs())
    except OSError:
        pass


def stop_process(pid):
    try:
        return subprocess.run(
            ['taskkill.exe', '/PID', str(pid), '/T', '/F'],
            capture_output=True, **hidden_kwargs(),
        ).returncode == 0
    except OSError:
        return False


def wait_for_process_exit(pid, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.2)
    return not process_alive(pid)


def rclone_path(root):
    candidate = Path(root) / 'tools' / 'rclone.exe'
    if candidate.exists():
        return candidate
    candidate = bundled_root() / 'tools' / 'rclone.exe'
    return candidate if candidate.exists() else None


def validate_mount_item(item):
    name = str(item.name).strip()
    drive = str(item.drive).strip().rstrip(':').upper()
    url = str(item.url).strip()
    if not name:
        raise ValueError('挂载方案名称不能为空')
    if drive not in MOUNT_LETTERS:
        raise ValueError(f'盘符必须是 D: 到 Z:，当前为 {item.drive!r}')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        raise ValueError(f'服务地址必须是有效的 HTTP/HTTPS 地址: {url!r}')
    if len(str(item.path)) > 1024 or '\\x00' in str(item.path):
        raise ValueError('子路径无效')
    item.name = name
    item.drive = drive
    item.url = url.rstrip('/')
    item.path = str(item.path).strip().replace('\\\\', '/')
    return item


def mount_source(item):
    return webdav_url(item)


def append_engine_log(root, text):
    log_path = root / 'logs' / 'engine.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open('a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S ') + text + '\n')
    except OSError:
        pass
    try:
        lines = log_path.read_text(encoding='utf-8').splitlines()
        if len(lines) > LOG_TAIL:
            log_path.write_text('\n'.join(lines[-LOG_TAIL:]) + '\n', encoding='utf-8')
    except OSError:
        pass


def _stop_mount(root, item, emit):
    pids_path = managed_mount(root, item)
    pid = None
    if pids_path.exists():
        try:
            data = json.loads(pids_path.read_text(encoding='utf-8'))
            pid = data.get(item.id)
        except (OSError, ValueError):
            pid = None
    if pid and process_alive(pid):
        emit(f'正在停止 rclone 进程 PID={pid}…')
        if not stop_process(pid) or not wait_for_process_exit(pid):
            raise RuntimeError(f'rclone 进程 PID={pid} 未能停止')
    if drive_ready(item.drive):
        emit(f'正在释放盘符 {item.drive}:…')
        # rclone/WinFsp 盘符不是传统 net use 映射，net.exe 仅作为兼容性清理，
        # 最终结果以盘符是否消失为准。
        subprocess.run(['net.exe', 'use', f'{item.drive}:', '/delete', '/y'],
                       capture_output=True, **hidden_kwargs())
        refresh_explorer_drive(item.drive, added=False)
    if not wait_for_drive_state(item.drive, mounted=False):
        raise RuntimeError(f'盘符 {item.drive}: 仍处于挂载状态')
    emit(f'已卸载 {item.drive}:')
    try:
        if pids_path.exists():
            data = json.loads(pids_path.read_text(encoding='utf-8'))
            data.pop(item.id, None)
            pids_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except (OSError, ValueError) as exc:
        emit(f'清理进程记录失败：{exc}')


def stop_mount(root, item, emit):
    _stop_mount(root, item, emit)


def wait_for_drive_state(letter, mounted=False, timeout=8.0):
    """等待盘符达到目标状态，避免进程刚结束时立即误判卸载失败。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if drive_ready(letter) is mounted:
            return True
        time.sleep(0.2)
    return drive_ready(letter) is mounted


def remote_probe(root, item):
    """探活: 确认 Alist/webdav 可访问 + 路径存在。"""
    rclone = rclone_path(root)
    if rclone is None:
        return False, 'rclone 不存在'
    env = clean_env()
    remote = f'cloud_{re.sub(r"[^a-zA-Z0-9]", "", item.id)}'
    config_dir = root / 'config'
    config_dir.mkdir(parents=True, exist_ok=True)
    conf_path = config_dir / 'rclone.conf'
    conf_backup = None
    if conf_path.exists():
        conf_backup = conf_path.read_bytes()
    try:
        item_pass = getattr(item, 'passwd', '')
        lines = [f'[{remote}]', 'type = webdav', f'url = {webdav_url(item)}',
                 'vendor = other', f'user = {item.user}', f'pass = {item_pass}']
        conf_path.write_bytes(('\n'.join(lines) + '\n').encode('utf-8'))
        result = subprocess.run(
            [str(rclone), 'lsd', f'{remote}:', '--config', str(conf_path)],
            capture_output=True, timeout=30, env=env, **hidden_kwargs()
        )
        if result.returncode == 0:
            return True, ''
        err = result.stderr.decode('utf-8', errors='replace')
        return False, err or '无法访问'
    except subprocess.TimeoutExpired:
        return False, '连接超时'
    except OSError as exc:
        return False, str(exc)
    finally:
        if conf_backup is not None:
            conf_path.write_bytes(conf_backup)
        elif conf_path.exists():
            conf_path.unlink()


def _mount_all_unlocked(root, emit, fail_on_partial=True, only_id=None):
    settings = load_settings(root)
    items = []
    for raw in settings.get('items', []):
        if not raw.get('enabled', True):
            continue
        items.append(validate_mount_item(Item.from_dict(raw)))
    if only_id:
        items = [i for i in items if i.id == only_id]
    drives = [item.drive for item in items]
    if len(drives) != len(set(drives)):
        duplicates = sorted({drive for drive in drives if drives.count(drive) > 1})
        raise ValueError(f'存在重复盘符配置：{", ".join(f"{drive}:" for drive in duplicates)}')
    if not items:
        emit('没有已配置的挂载方案')
        return {'mounted': 0, 'failed': 0, 'items': []}
    write_rclone_config(root, settings)
    needs_alist = any(item.type != 'WebDAV' for item in items)
    if needs_alist and not port_open(ALIST_PORT):
        start_alist(root)
        for _ in range(ALIST_READY_TIMEOUT):
            if port_open(ALIST_PORT):
                break
            time.sleep(1)
    mounted, failed = 0, 0
    results = []
    for item in items:
        if not drive_ready(item.drive):
            try:
                remote_probe(root, item)
            except Exception:
                pass
        rclone = rclone_path(root)
        if rclone is None:
            raise FileNotFoundError('rclone 不存在')
        remote = f'cloud_{re.sub(r"[^a-zA-Z0-9]", "", item.id)}'
        log_file = root / 'logs' / f'rclone_{item.drive}.log'
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_file.open('wb')
        try:
            proc = subprocess.Popen(
                [str(rclone), 'mount', f'{remote}:', f'{item.drive}:',
                 '--config', str(root / 'config' / 'rclone.conf'),
                 '--volname', item.name,
                 '--vfs-cache-mode', 'full', '--log-file', str(log_file), '--log-level', 'INFO'],
                env=clean_env(), stdout=log_handle, stderr=subprocess.STDOUT, **hidden_kwargs()
            )
            time.sleep(0.5)
            if drive_ready(item.drive):
                mounted += 1
                results.append({'id': item.id, 'drive': item.drive, 'pid': proc.pid, 'ok': True})
                refresh_explorer_drive(item.drive, added=True)
                pids_path = root / 'logs' / 'rclone_pids.json'
                data = {}
                if pids_path.exists():
                    try:
                        data = json.loads(pids_path.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        data = {}
                data[item.id] = proc.pid
                pids_path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                emit(f'挂载成功：{item.drive}: → {item.name}')
            else:
                failed += 1
                results.append({'id': item.id, 'drive': item.drive, 'pid': proc.pid, 'ok': False})
                stop_process(proc.pid)
                emit(f'挂载失败：{item.drive}: → {item.name}')
        except OSError as exc:
            failed += 1
            results.append({'id': item.id, 'drive': item.drive, 'ok': False, 'error': str(exc)})
            emit(f'挂载失败：{item.drive}: → {exc}')
        finally:
            log_handle.close()
    if failed and fail_on_partial:
        if mounted == 0:
            raise RuntimeError('没有方案挂载成功：' + '; '.join(r.get('error', '') for r in results if not r.get('ok')))
    return {'mounted': mounted, 'failed': failed, 'items': results}


def mount_all(root, emit, fail_on_partial=True, only_id=None):
    with acquire_mount_lock(root):
        return _mount_all_unlocked(root, emit, fail_on_partial, only_id)


def health_check(root):
    """健康检查：发现挂载丢失则自动重挂。"""
    settings = load_settings(root)
    items = settings.get('items', [])
    if not items:
        return
    for item in items:
        if not item.get('enabled', True):
            continue
        if not drive_ready(item.drive):
            pids_path = root / 'logs' / 'rclone_pids.json'
            tracked = False
            if pids_path.exists():
                try:
                    data = json.loads(pids_path.read_text(encoding='utf-8'))
                    pid = data.get(item.id)
                    tracked = bool(pid and process_alive(pid))
                except (OSError, ValueError):
                    pass
            if tracked:
                try:
                    stop_process(int(pid))
                except Exception:
                    pass
            try:
                mount_all(root, lambda t: None, fail_on_partial=False, only_id=item.id)
            except Exception as exc:
                append_engine_log(root, f'健康检查修复失败: {exc}')


def startup(root):
    clear_legacy_network_locations()
    mount_all(root, lambda t: None, fail_on_partial=True)


def write_task_result(result_path, ok, message):
    result_path = Path(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'ok': bool(ok),
        'message': message if ok else '',
        'error': message if not ok else '',
    }
    result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def install_dir():
    """mount_wizard.exe 所在目录（即安装目录）。"""
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def release_drivers(root=None):
    """强制重新释放 Alist / rclone 到 runtime/tools。删除残留后从 bundle 重新复制。"""
    if root is None:
        root = runtime_root()
    if not frozen():
        return False, '仅在打包后可用'
    tools_dst = root / 'tools'
    if tools_dst.exists():
        try:
            shutil.rmtree(tools_dst)
        except OSError as exc:
            return False, f'无法删除 {tools_dst}: {exc}'
    source = bundled_root() / 'tools'
    if not source.is_dir():
        return False, 'bundle 中找不到 tools/'
    try:
        shutil.copytree(source, tools_dst)
    except OSError as exc:
        return False, f'复制失败: {exc}'
    alist = tools_dst / 'alist.exe'
    rclone = tools_dst / 'rclone.exe'
    ok = alist.exists() and rclone.exists()
    return ok, ('驱动已重新释放' if ok else '释放后仍缺少文件')


def request_winfsp_install():
    """通过 UAC 提权来安装 WinFsp。"""
    msi = install_dir() / 'tools' / 'winfsp.msi'
    if not msi.exists():
        return False, f'找不到 WinFsp 安装包：{msi}'
    log_path = install_dir() / 'runtime' / 'logs' / 'winfsp-install.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = f'msiexec.exe /i "{msi}" /qn /norestart /L*v "{log_path}"'
    try:
        ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'cmd.exe', f'/c {cmd}', None, 0)
    except Exception as exc:
        return False, f'提权启动失败: {exc}'
    return True, '已请求安装'


class Item:
    """挂载方案"""
    def __init__(self, id=None, name='', type='WebDAV', url='', user='admin', passwd='', drive='Y', path='', enabled=True):
        self.id = id or str(uuid.uuid4())
        self.name = name
        self.type = type
        self.url = url
        self.user = user
        self.passwd = passwd  # 内部用 passwd 避免与关键字 pass 冲突；JSON 键保持 'pass'
        self.drive = drive
        self.path = path
        self.enabled = enabled

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'url': self.url,
            'user': self.user,
            'pass': self.passwd,
            'drive': self.drive,
            'path': self.path,
            'enabled': self.enabled,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d.get('id'),
            name=d.get('name', ''),
            type=d.get('type', 'WebDAV'),
            url=d.get('url', ''),
            user=d.get('user', 'admin'),
            passwd=d.get('pass', ''),
            drive=d.get('drive', 'Y'),
            path=d.get('path', ''),
            enabled=d.get('enabled', True),
        )


# ==================== 共享 UI 基类 ====================

class BaseWindow(tk.Tk):
    """带磨砂玻璃 + 主题切换的窗口基类。"""

    def __init__(self, title, width, height):
        super().__init__()
        self.title(title)
        self.geometry(f'{width}x{height}')
        self.minsize(max(760, int(width * 0.85)), max(560, int(height * 0.80)))
        self.theme = Theme(self)
        self.events = queue.Queue()
        self.busy = False
        self._poll_after = None
        self._apply_theme_colors()

    def _apply_theme_colors(self):
        c = self.theme.c
        self.configure(bg=c['bg'])
        self.option_add('*Font', (ui_theme.FONT, 10))
        self.theme.apply_glass()

    def toggle_theme(self):
        self.theme.toggle()
        self._apply_theme_colors()
        self.refresh_theme()

    def refresh_theme(self):
        """子类重写：主题切换后刷新需要显式颜色的控件。"""
        pass

    def run_async(self, action, on_done=None, on_error=None):
        """在后台线程执行 action，并在 Tk 主线程回调结果。"""
        if self.busy:
            return
        self.busy = True
        self._async_done = on_done
        self._async_error = on_error
        self.on_busy_changed()

        def worker():
            emit = lambda text: self.events.put(('log', text))
            progress = lambda value: self.events.put(('progress', value))
            try:
                result = action(emit, progress)
                self.events.put(('done', result or {}))
            except Exception as exc:
                self.events.put(('error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def on_busy_changed(self):
        pass

    def poll_events(self, on_log=None, on_done=None, on_error=None):
        try:
            if not self.winfo_exists():
                return
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'log' and on_log:
                    on_log(payload)
                elif kind == 'done':
                    self.busy = False
                    self.on_busy_changed()
                    callback = getattr(self, '_async_done', None)
                    self._async_done = None
                    self._async_error = None
                    if callback:
                        callback(payload)
                    elif on_done:
                        on_done(payload)
                elif kind == 'error':
                    self.busy = False
                    self.on_busy_changed()
                    callback = getattr(self, '_async_error', None)
                    self._async_done = None
                    self._async_error = None
                    if callback:
                        callback(payload)
                    elif on_error:
                        on_error(payload)
                    else:
                        messagebox.showerror(APP_TITLE, str(payload))
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            if self.winfo_exists():
                self._poll_after = self.after(200, lambda: self.poll_events(on_log, on_done, on_error))
        except tk.TclError:
            self._poll_after = None

    def destroy(self):
        if self._poll_after:
            try:
                self.after_cancel(self._poll_after)
            except tk.TclError:
                pass
            self._poll_after = None
        super().destroy()


# ==================== 鱼骨式分步向导 ====================

class SetupWizard(BaseWindow):
    """首次配置的鱼骨式分步向导。"""

    STEPS = [
        ('环境检查', '检测 WinFsp / Alist / rclone 驱动'),
        ('Alist 服务', '设置本机 Alist 管理员密码'),
        ('挂载方案', '添加要挂载的网盘'),
        ('确认配置', '确认并立即挂载'),
        ('完成', '进入控制台'),
    ]

    def __init__(self, root):
        super().__init__(f'{APP_TITLE} · 配置向导', 980, 700)
        self.root_dir = Path(root)
        self.settings = load_settings(self.root_dir)
        self.step = 0
        self._build_header()
        self._build_body()
        self._build_footer()
        self._render_step()
        self.after(200, self._poll)

    def _build_header(self):
        header = ttk.Frame(self)
        header.pack(fill='x', padx=32, pady=(24, 12))
        top = ttk.Frame(header)
        top.pack(fill='x')
        ttk.Label(top, text=APP_TITLE, style='Title.TLabel').pack(side='left')
        self.theme_btn = ttk.Button(top,
                                    text='切换到浅色' if self.theme.mode == 'dark' else '切换到深色',
                                    style='ThemeToggle.TButton', command=self.toggle_theme)
        self.theme_btn.pack(side='right')
        self._build_fishbone(header)

    def _build_fishbone(self, parent):
        """鱼骨式步骤指示器。"""
        bone = ui_theme.glass_frame(parent, self.theme, elevated=False)
        bone.pack(fill='x', pady=(16, 4))
        self.step_nodes = []
        for i, (title, _) in enumerate(self.STEPS):
            node = ui_theme.glass_frame(bone, self.theme, elevated=True)
            node.pack(side='left', fill='x', expand=True)
            dot = ui_theme.glass_label(node, self.theme, str(i + 1), width=3, height=1,
                                       fg=self.theme.c['muted'], font=(ui_theme.FONT, 11, 'bold'))
            dot.pack(pady=(0, 2))
            lbl = ui_theme.glass_label(node, self.theme, title, muted=True,
                                       font=(ui_theme.FONT, 9))
            lbl.pack()
            self.step_nodes.append((node, dot, lbl))
        self._update_fishbone()

    def _update_fishbone(self):
        c = self.theme.c
        for i, (node, dot, lbl) in enumerate(self.step_nodes):
            node.configure(bg=c['surface2'])
            lbl.configure(bg=c['surface2'])
            if i < self.step:
                dot.configure(bg=c['success'], fg='#ffffff')
                lbl.configure(fg=c['success'])
            elif i == self.step:
                dot.configure(bg=c['accent'], fg='#ffffff')
                lbl.configure(fg=c['accent'])
            else:
                dot.configure(bg=c['surface2'], fg=c['muted'])
                lbl.configure(fg=c['muted'])

    def _build_body(self):
        self.card = ttk.Frame(self, style='Surface.TFrame')
        self.card.pack(fill='both', expand=True, padx=32, pady=(0, 12))
        self.content = ttk.Frame(self.card, style='Surface.TFrame')
        self.content.pack(fill='both', expand=True, padx=28, pady=22)

    def _build_footer(self):
        footer = ttk.Frame(self)
        footer.pack(fill='x', padx=32, pady=(0, 22))
        self.hint = ttk.Label(footer, text='', style='Muted.TLabel')
        self.hint.pack(side='left')
        self.back_btn = ttk.Button(footer, text='上一步', command=self._back)
        self.back_btn.pack(side='right', padx=(0, 10))
        self.next_btn = ttk.Button(footer, text='下一步', style='Primary.TButton', command=self._next)
        self.next_btn.pack(side='right')

    def _render_step(self):
        for w in self.content.winfo_children():
            w.destroy()
        self._update_fishbone()
        self.back_btn.configure(state=('disabled' if self.step == 0 or self.busy else 'normal'))
        self.next_btn.configure(state=('disabled' if self.busy else 'normal'))
        getattr(self, f'_step_{self.step}')()

    def _heading(self, title, text):
        ttk.Label(self.content, text=title, style='Heading.TLabel').pack(anchor='w')
        ttk.Label(self.content, text=text, style='SurfaceMuted.TLabel',
                  wraplength=820, justify='left').pack(anchor='w', pady=(8, 18))

    def _info_row(self, title, detail, ok, action=None):
        c = self.theme.c
        row = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        row.pack(fill='x', pady=5)
        ui_theme.glass_label(row, self.theme, title, font=(ui_theme.FONT, 10, 'bold'),
                              width=12, anchor='w').pack(side='left', padx=16, pady=12)
        ui_theme.glass_label(row, self.theme, detail, muted=True).pack(side='left', padx=4)
        ui_theme.glass_label(row, self.theme, '就绪' if ok else '需要处理',
                              fg=c['success'] if ok else c['warning'],
                              font=(ui_theme.FONT, 10, 'bold')).pack(side='right', padx=16)
        if action:
            ttk.Button(row, text=action[0], command=action[1]).pack(side='right', padx=8, pady=6)

    # ---- 步骤 0：环境检查 ----
    def _step_0(self):
        self._heading('环境检查', '向导使用 Alist、rclone 与 WinFsp 架构，可把多个网盘挂载为本地盘符。')
        checks = [
            ('WinFsp 驱动', '负责在 Windows 中创建本地盘符', winfsp_installed()),
            ('Alist', '聚合天翼、移动、阿里云盘等服务', (self.root_dir / 'tools' / 'alist.exe').exists()),
            ('rclone', '执行 WebDAV 到盘符的挂载', (self.root_dir / 'tools' / 'rclone.exe').exists()),
        ]
        for title, detail, ok in checks:
            action = None
            if not ok:
                action = ('安装 WinFsp', self._install_winfsp) if title == 'WinFsp 驱动' else ('释放驱动', lambda t=title: self._release(t))
            self._info_row(title, detail, ok, action)
        ttk.Label(self.content, text='WinFsp 安装后需重启一次 Windows 才能完全生效。',
                  style='SurfaceMuted.TLabel').pack(anchor='w', pady=(16, 0))
        self.hint.configure(text='确认环境后继续')

    def _install_winfsp(self):
        msi = install_dir() / 'tools' / 'winfsp.msi'
        if not msi.exists():
            messagebox.showerror(APP_TITLE, f'找不到 WinFsp 安装包：\n{msi}\n\n请重新运行安装程序。')
            return
        if messagebox.askyesno(APP_TITLE, '即将请求管理员权限安装 WinFsp，完成后需重启一次。\n\n是否继续？'):
            ok, msg = request_winfsp_install()
            messagebox.showinfo(APP_TITLE, '已请求安装' if ok else f'失败：{msg}')

    def _release(self, driver):
        def work(emit, progress):
            emit(f'正在释放 {driver}...')
            ok, msg = release_drivers(self.root_dir)
            if not ok:
                raise RuntimeError(msg)
            return {'msg': msg}
        self.run_async(work)

    # ---- 步骤 1：Alist 服务 ----
    def _step_1(self):
        self._heading('设置 Alist 本机服务', '天翼云盘、移动云盘等通过 Alist 管理账号授权。标准 WebDAV 不依赖此处。')
        form = ttk.Frame(self.content, style='Surface.TFrame')
        form.pack(fill='x')
        ttk.Label(form, text='管理员账号', style='Surface.TLabel', width=16).grid(row=0, column=0, sticky='w', pady=8)
        ttk.Label(form, text='admin（Alist 默认管理员）', style='SurfaceMuted.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Label(form, text='管理员密码', style='Surface.TLabel', width=16).grid(row=1, column=0, sticky='w', pady=8)
        self.alist_password = tk.StringVar(value=self.settings.get('alist_pass', ''))
        ttk.Entry(form, textvariable=self.alist_password, show='*', width=36).grid(row=1, column=1, sticky='w')
        ttk.Label(form, text='首次设置请输入密码；留空则沿用已保存的加密凭据', style='SurfaceMuted.TLabel').grid(row=2, column=1, sticky='w')
        btn_row = ttk.Frame(self.content, style='Surface.TFrame')
        btn_row.pack(fill='x', pady=(22, 0))
        ttk.Button(btn_row, text='保存并初始化', style='Primary.TButton', command=self._save_alist).pack(side='left')
        ttk.Button(btn_row, text='启动 Alist', command=self._launch_alist).pack(side='left', padx=10)
        ttk.Button(btn_row, text='打开管理后台', command=self._open_alist).pack(side='left', padx=10)
        state = 'Alist 当前正在运行' if port_open() else 'Alist 当前未启动'
        ttk.Label(self.content, text=state, style='SurfaceMuted.TLabel').pack(anchor='w', pady=(18, 0))
        self.hint.configure(text='下一步将配置挂载方案')

    def _save_alist(self):
        if self.busy:
            return
        password = self.alist_password.get().strip()
        if password:
            try:
                alist_exe = str(self.root_dir / 'tools' / 'alist.exe')
                run_capture([alist_exe, 'admin', 'set', password], self.root_dir, env=clean_env())
                self.settings['alist_pass'] = obscure(self.root_dir, password)
            except Exception as exc:
                messagebox.showerror(APP_TITLE, str(exc))
                return
        elif not self.settings.get('alist_pass'):
            messagebox.showwarning(APP_TITLE, '首次设置请输入 Alist 管理员密码。')
            return
        self.settings['alist_user'] = 'admin'
        write_rclone_config(self.root_dir, self.settings)
        save_settings(self.root_dir, self.settings)
        messagebox.showinfo(APP_TITLE, 'Alist 设置已保存。')

    def _launch_alist(self):
        def work(emit, progress):
            emit('正在启动 Alist…')
            start_alist(self.root_dir)
            emit('Alist 已就绪')
        self.run_async(work)

    def _open_alist(self):
        if self.busy:
            return
        if port_open(ALIST_PORT):
            self._open_webview(ALIST_URL, 'Alist 管理后台')
            return

        def work(emit, progress):
            emit('正在启动 Alist 管理后台…')
            start_alist(self.root_dir)
            return {'open_url': ALIST_URL}

        def on_done(payload):
            url = payload.get('open_url') if isinstance(payload, dict) else ALIST_URL
            self._open_webview(url, 'Alist 管理后台')

        def on_error(error):
            messagebox.showerror(APP_TITLE, f'Alist 启动失败：{error}')

        self.run_async(work, on_done=on_done, on_error=on_error)

    def _open_webview(self, url, title):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            messagebox.showerror(APP_TITLE, '管理后台地址无效')
            return
        # Windows 下交给默认浏览器，避免 pywebview 消息循环在后台线程中无窗口。
        try:
            if os.name == 'nt':
                os.startfile(url)
            elif not webbrowser.open(url, new=2):
                raise OSError('默认浏览器未接受打开请求')
        except (OSError, webbrowser.Error) as exc:
            messagebox.showerror(APP_TITLE, f'无法打开管理后台：{exc}')

    # ---- 步骤 2：挂载方案 ----
    def _step_2(self):
        self._heading('添加挂载方案', '每个方案选择网盘类型与盘符。标准 WebDAV 填地址和账号；其他类型先在 Alist 后台添加存储。')
        items = self.settings.get('items', [])
        if not items:
            tk.Label(self.content, text='还没有挂载方案\n\n例如：WebDAV → D:  ·  天翼云盘 → E:',
                     bg=self.theme.c['surface'], fg=self.theme.c['muted'],
                     font=(ui_theme.FONT, 11), justify='left').pack(anchor='w', pady=18)
        else:
            for item_dict in items:
                item = Item.from_dict(item_dict)
                self._mount_row(item)
        ttk.Button(self.content, text='＋ 新建挂载方案', style='Primary.TButton',
                   command=lambda: self._edit_mount(None)).pack(anchor='w', pady=(18, 0))
        self.hint.configure(text='可以添加多个不同盘符')

    def _mount_row(self, item):
        c = self.theme.c
        row = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        row.pack(fill='x', pady=5)
        ui_theme.glass_label(row, self.theme, item.name or '(未命名)',
                              font=(ui_theme.FONT, 10, 'bold'), width=20,
                              anchor='w').pack(side='left', padx=14, pady=10)
        ui_theme.glass_label(row, self.theme, f'{item.type} → {item.drive}:',
                              muted=True).pack(side='left', padx=4)
        ttk.Button(row, text='编辑', command=lambda: self._edit_mount(item.id)).pack(side='right', padx=8, pady=6)
        ttk.Button(row, text='删除', command=lambda: self._delete_mount(item.id)).pack(side='right', padx=4, pady=6)

    def _edit_mount(self, edit_id):
        existing = next((Item.from_dict(i) for i in self.settings.get('items', []) if i.get('id') == edit_id), Item())
        dlg = MountDialog(self, existing, self.theme)
        self.wait_window(dlg)
        if dlg.result:
            items = [i for i in self.settings.get('items', []) if i.get('id') != dlg.result.id] + [dlg.result.to_dict()]
            self.settings['items'] = items
            save_settings(self.root_dir, self.settings)
            self._render_step()

    def _delete_mount(self, item_id):
        if messagebox.askyesno(APP_TITLE, '确认删除该挂载方案？'):
            items = [i for i in self.settings.get('items', []) if i.get('id') != item_id]
            self.settings['items'] = items
            save_settings(self.root_dir, self.settings)
            self._render_step()

    # ---- 步骤 3：确认配置 ----
    def _step_3(self):
        self._heading('确认配置', '可以立即挂载全部方案，也可安装登录自动挂载与每 3 分钟健康检查。')
        items = self.settings.get('items', [])
        if not items:
            ttk.Label(self.content, text='请至少添加一个挂载方案。', style='SurfaceMuted.TLabel').pack(anchor='w', pady=16)
        else:
            ttk.Label(self.content, text=f'已配置 {len(items)} 个挂载方案', style='SurfaceMuted.TLabel').pack(anchor='w', pady=8)
        btn_row = ttk.Frame(self.content, style='Surface.TFrame')
        btn_row.pack(fill='x', pady=(20, 0))
        ttk.Button(btn_row, text='立即挂载全部', style='Primary.TButton', command=self._mount_all).pack(side='left')
        ttk.Button(btn_row, text='安装自动维护', command=self._install_tasks).pack(side='left', padx=10)
        self.hint.configure(text='最后一步完成')

    def _mount_all(self):
        def work(emit, progress):
            r = mount_all(self.root_dir, emit, fail_on_partial=True)
            return {'msg': f'成功 {r["mounted"]} 个'}
        self.run_async(work)

    def _install_tasks(self):
        try:
            request_task_install(self.root_dir)
            messagebox.showinfo(APP_TITLE, '自动维护任务安装完成：登录时启动 Alist 并挂载，每 3 分钟健康检查。')
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f'登录自动启动失败: {exc}')

    # ---- 步骤 4：完成 ----
    def _step_4(self):
        self._heading('配置完成', '所有步骤已结束，现在进入控制台。')
        ttk.Label(self.content, text='✓ 配置已就绪', style='SurfaceMuted.TLabel').pack(anchor='w', pady=16)
        ttk.Label(self.content, text='进入控制台后，可管理挂载、启动 Alist、查看日志。',
                  style='SurfaceMuted.TLabel').pack(anchor='w')
        self.next_btn.configure(text='进入控制台')

    def _back(self):
        if self.step > 0:
            self.step -= 1
            self._render_step()

    def _next(self):
        if self.step == 1 and not self.settings.get('alist_pass') and not self.alist_password.get().strip():
            messagebox.showwarning(APP_TITLE, '请先设置 Alist 管理员密码。')
            return
        if self.step == 2 and not self.settings.get('items'):
            messagebox.showwarning(APP_TITLE, '请至少添加一个挂载方案。')
            return
        if self.step >= len(self.STEPS) - 1:
            self.destroy()
            Console(self.root_dir).mainloop()
            return
        self.step += 1
        self._render_step()

    def refresh_theme(self):
        self._render_step()
        self.theme_btn.configure(text='切换到浅色' if self.theme.mode == 'dark' else '切换到深色')

    def _poll(self):
        def on_log(t):
            self.hint.configure(text=t)
        def on_done(p):
            self.busy = False
            self.hint.configure(text='—— 操作成功完成 ——')
            self._render_step()
        def on_error(p):
            self.hint.configure(text=f'—— 执行失败 ——\n{p}')
        self.poll_events(on_log, on_done, on_error)


# ==================== 控制台 ====================

class Console(BaseWindow):
    """控制台主页面：左侧分区导航 + 右侧内容。"""

    NAV = [
        ('挂载管理', 'mount'),
        ('Alist 服务', 'alist'),
        ('设置', 'settings'),
        ('日志', 'logs'),
        ('关于', 'about'),
    ]

    def __init__(self, root):
        super().__init__(f'{APP_TITLE} · 控制台', 1080, 720)
        self.root_dir = Path(root)
        self.settings = load_settings(self.root_dir)
        self.active = 'mount'
        self._build_nav()
        self._build_main()
        self._render_page()
        self.after(200, self._poll)

    def _build_nav(self):
        c = self.theme.c
        self.nav = ui_theme.glass_frame(self, self.theme, elevated=False, width=220)
        self.nav.pack(side='left', fill='y')
        self.nav.pack_propagate(False)
        self.nav_title = ui_theme.glass_label(self.nav, self.theme, APP_TITLE,
                                              font=(ui_theme.FONT, 15, 'bold'), bg=c['surface'])
        self.nav_title.pack(anchor='w', padx=20, pady=(24, 8))
        self.nav_subtitle = ui_theme.glass_label(self.nav, self.theme, '控制台', muted=True,
                                                 font=(ui_theme.FONT, 10), bg=c['surface'])
        self.nav_subtitle.pack(anchor='w', padx=20, pady=(0, 20))
        self.nav_buttons = {}
        for label, key in self.NAV:
            btn = tk.Button(self.nav, text=label, anchor='w', relief='flat', bd=0,
                            bg=c['surface'], fg=c['muted'], activebackground=c['surface2'],
                            activeforeground=c['text'], font=(ui_theme.FONT, 11),
                            padx=20, pady=12, command=lambda k=key: self._switch(k))
            btn.pack(fill='x')
            self.nav_buttons[key] = btn
        self.theme_btn = tk.Button(self.nav,
                                   text='切换到浅色' if self.theme.mode == 'dark' else '切换到深色',
                                   relief='flat', bd=0, highlightthickness=0,
                                   bg=c['surface'], fg=c['muted'],
                                   activebackground=c['surface2'], activeforeground=c['text'],
                                   disabledforeground=c['muted'],
                                   font=(ui_theme.FONT, 9, 'bold'),
                                   padx=10, pady=6, command=self.toggle_theme,
                                   cursor='hand2')
        self.theme_btn.pack(side='bottom', pady=16)
        self._update_nav()

    def _update_nav(self):
        c = self.theme.c
        for key, btn in self.nav_buttons.items():
            active = (key == self.active)
            btn.configure(
                bg=c['accent'] if active else c['surface'],
                fg='#ffffff' if active else c['muted'],
                activebackground=c['accent_hover'] if active else c['glass_hover'],
                activeforeground='#ffffff' if active else c['text'],
            )

    def _build_main(self):
        c = self.theme.c
        self.main = ttk.Frame(self, style='Surface.TFrame')
        self.main.pack(side='left', fill='both', expand=True)
        self.content = ttk.Frame(self.main, style='Surface.TFrame')
        self.content.pack(fill='both', expand=True, padx=28, pady=24)
        self._content_root = self.content

    def _switch(self, key):
        self.active = key
        self._update_nav()
        self._render_page()

    def _render_page(self):
        self.content = self._content_root
        for w in self.content.winfo_children():
            w.destroy()
        getattr(self, f'_page_{self.active}')()

    def _page_heading(self, title, text=''):
        ttk.Label(self.content, text=title, style='Heading.TLabel').pack(anchor='w')
        if text:
            ttk.Label(self.content, text=text, style='SurfaceMuted.TLabel',
                      wraplength=780, justify='left').pack(anchor='w', pady=(6, 16))

    # ---- 挂载管理 ----
    def _page_mount(self):
        self._operation_buttons = []
        self._page_heading('挂载管理', '增删改查挂载方案，并执行挂载 / 卸载。')
        status_text = getattr(self, '_pending_operation_status', '')
        self._pending_operation_status = ''
        self.operation_status = ttk.Label(self.content, text=status_text, style='SurfaceMuted.TLabel')
        self.operation_status.pack(anchor='w', pady=(0, 8))
        toolbar = ttk.Frame(self.content, style='Surface.TFrame')
        toolbar.pack(fill='x', pady=(0, 12))
        self._add_operation_button(ttk.Button(
            toolbar, text='＋ 新建方案', style='Primary.TButton',
            command=lambda: self._edit_mount(None),
        )).pack(side='left')
        self._add_operation_button(ttk.Button(
            toolbar, text='挂载全部', style='Primary.TButton', command=self._mount_all,
        )).pack(side='left', padx=8)
        self._add_operation_button(ttk.Button(
            toolbar, text='全部卸载', style='Danger.TButton', command=self._unmount_all,
        )).pack(side='left', padx=8)
        items = self.settings.get('items', [])
        if not items:
            tk.Label(self.content, text='暂无挂载方案，点击「新建方案」添加。',
                     bg=self.theme.c['surface'], fg=self.theme.c['muted'],
                     font=(ui_theme.FONT, 11)).pack(anchor='w', pady=24)
            return
        for item_dict in items:
            item = Item.from_dict(item_dict)
            self._mount_card(item)

    def _add_operation_button(self, button):
        self._operation_buttons.append(button)
        return button

    def _update_operation_buttons(self):
        state = 'disabled' if self.busy else 'normal'
        for button in getattr(self, '_operation_buttons', []):
            try:
                if button.winfo_exists():
                    button.configure(state=state)
            except tk.TclError:
                continue

    def _mount_card(self, item):
        c = self.theme.c
        mounted = drive_ready(item.drive)
        card = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        card.pack(fill='x', pady=6)
        head = tk.Frame(card, bg=c['surface2'], bd=0, highlightthickness=0)
        head.pack(fill='x', padx=16, pady=(12, 4))
        ui_theme.glass_label(head, self.theme, item.name or '(未命名)',
                              font=(ui_theme.FONT, 11, 'bold')).pack(side='left')
        state = '已挂载' if mounted else '未挂载'
        ui_theme.glass_label(head, self.theme, state,
                              fg=c['success'] if mounted else c['muted'],
                              font=(ui_theme.FONT, 9, 'bold')).pack(side='right')
        sub = tk.Frame(card, bg=c['surface2'], bd=0, highlightthickness=0)
        sub.pack(fill='x', padx=16, pady=(0, 12))
        ui_theme.glass_label(sub, self.theme, f'{item.type} → {item.drive}:  ·  {item.url}',
                              muted=True, font=(ui_theme.FONT, 9)).pack(side='left')
        action_btn = self._add_operation_button(ttk.Button(
            sub, text='卸载' if mounted else '挂载',
            style='Danger.TButton' if mounted else 'TButton',
            command=lambda: self._toggle_mount(item),
        ))
        action_btn.pack(side='right', padx=4)
        edit_btn = self._add_operation_button(ttk.Button(
            sub, text='编辑', command=lambda: self._edit_mount(item.id),
        ))
        edit_btn.pack(side='right', padx=4)
        delete_btn = self._add_operation_button(ttk.Button(
            sub, text='删除', style='Danger.TButton',
            command=lambda: self._delete_mount(item.id),
        ))
        delete_btn.pack(side='right', padx=4)

    def _edit_mount(self, edit_id):
        existing = next((Item.from_dict(i) for i in self.settings.get('items', []) if i.get('id') == edit_id), Item())
        dlg = MountDialog(self, existing, self.theme)
        self.wait_window(dlg)
        if dlg.result:
            items = [i for i in self.settings.get('items', []) if i.get('id') != dlg.result.id] + [dlg.result.to_dict()]
            self.settings['items'] = items
            save_settings(self.root_dir, self.settings)
            self._render_page()

    def _delete_mount(self, item_id):
        if self.busy:
            return
        item = next((Item.from_dict(i) for i in self.settings.get('items', []) if i.get('id') == item_id), None)
        if item is None:
            return
        if drive_ready(item.drive) and not messagebox.askyesno(
            APP_TITLE, f'{item.drive}: 当前已挂载，删除前先卸载？', parent=self
        ):
            return
        if not messagebox.askyesno(APP_TITLE, '确认删除该挂载方案？删除后将从配置中移除。', parent=self):
            return

        def work(emit, progress):
            if drive_ready(item.drive):
                stop_mount(self.root_dir, item, emit)
            return {'removed_id': item.id, 'msg': f'已删除方案：{item.name}'}

        def on_done(payload):
            self.settings['items'] = [
                i for i in self.settings.get('items', []) if i.get('id') != item.id
            ]
            save_settings(self.root_dir, self.settings)
            self._render_page()

        self.run_async(work, on_done=on_done, on_error=self._show_async_error)

    def _show_async_error(self, error):
        self._pending_operation_status = f'操作失败：{error}'
        messagebox.showerror(APP_TITLE, str(error), parent=self)
        self._render_page()

    def on_busy_changed(self):
        self._update_operation_buttons()
        status = getattr(self, 'operation_status', None)
        if status is not None and status.winfo_exists() and self.busy:
            status.configure(text='正在执行操作，请稍候…')

    def _toggle_mount(self, item):
        if self.busy:
            return
        if drive_ready(item.drive):
            def work(emit, progress):
                stop_mount(self.root_dir, item, emit)
                return {'msg': f'已卸载 {item.drive}:'}
            self.run_async(
                work,
                on_done=lambda payload: self._operation_done(payload),
                on_error=self._show_async_error,
            )
        else:
            def work(emit, progress):
                mount_all(self.root_dir, emit, fail_on_partial=True, only_id=item.id)
                return {'msg': f'已挂载 {item.drive}:'}
            self.run_async(
                work,
                on_done=lambda payload: self._operation_done(payload),
                on_error=self._show_async_error,
            )

    def _operation_done(self, payload):
        self._pending_operation_status = payload.get('msg', '操作成功')
        self._render_page()

    def _mount_all(self):
        def work(emit, progress):
            r = mount_all(self.root_dir, emit, fail_on_partial=True)
            return {'msg': f'成功 {r["mounted"]} 个，失败 {r["failed"]} 个'}
        self.run_async(
            work,
            on_done=lambda payload: self._operation_done(payload),
            on_error=self._show_async_error,
        )

    def _unmount_all(self):
        if self.busy or not messagebox.askyesno(APP_TITLE, '确认取消所有挂载？', parent=self):
            return

        def work(emit, progress):
            errors = []
            for raw in self.settings.get('items', []):
                item = Item.from_dict(raw)
                try:
                    stop_mount(self.root_dir, item, emit)
                except Exception as exc:
                    errors.append(f'{item.drive}: {exc}')
            if errors:
                raise RuntimeError('部分盘符未能卸载：' + '; '.join(errors))
            emit('已取消全部挂载')
            return {'msg': '已取消全部挂载'}

        self.run_async(
            work,
            on_done=lambda payload: self._operation_done(payload),
            on_error=self._show_async_error,
        )

    # ---- Alist 服务 ----
    def _page_alist(self):
        self._page_heading('Alist 服务', '管理本机 Alist 服务，打开管理后台。')
        running = port_open()
        c = self.theme.c
        row = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        row.pack(fill='x', pady=6)
        ui_theme.glass_label(row, self.theme, 'Alist 服务', font=(ui_theme.FONT, 10, 'bold'),
                              width=14, anchor='w').pack(side='left', padx=16, pady=14)
        ui_theme.glass_label(row, self.theme, '运行中' if running else '已停止',
                              muted=not running, fg=c['success'] if running else c['muted'],
                              font=(ui_theme.FONT, 10, 'bold')).pack(side='left', padx=6)
        ttk.Button(row, text='停止' if running else '启动',
                   command=self._toggle_alist).pack(side='right', padx=10, pady=8)
        ttk.Button(row, text='打开管理后台', style='Primary.TButton',
                   command=self._open_alist).pack(side='right', padx=6, pady=8)
        ttk.Label(self.content, text=f'后台地址：{ALIST_URL}  ·  WebDAV：{ALIST_WEBDAV}',
                  style='SurfaceMuted.TLabel').pack(anchor='w', pady=(14, 0))

    def _toggle_alist(self):
        if port_open():
            stop_alist()
            self._render_page()
        else:
            def work(emit, progress):
                start_alist(self.root_dir)
                return {'msg': 'Alist 已启动'}
            self.run_async(work)

    def _open_alist(self):
        if self.busy:
            return
        if port_open(ALIST_PORT):
            self._open_webview(ALIST_URL, 'Alist 管理后台')
            return

        def work(emit, progress):
            emit('正在启动 Alist 管理后台…')
            start_alist(self.root_dir)
            return {'open_url': ALIST_URL}

        def on_done(payload):
            url = payload.get('open_url') if isinstance(payload, dict) else ALIST_URL
            self._open_webview(url, 'Alist 管理后台')

        def on_error(error):
            messagebox.showerror(APP_TITLE, f'Alist 启动失败：{error}')

        self.run_async(work, on_done=on_done, on_error=on_error)

    def _open_webview(self, url, title):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            messagebox.showerror(APP_TITLE, '管理后台地址无效')
            return
        # Windows 下交给默认浏览器，避免 pywebview 消息循环在后台线程中无窗口。
        try:
            if os.name == 'nt':
                os.startfile(url)
            elif not webbrowser.open(url, new=2):
                raise OSError('默认浏览器未接受打开请求')
        except (OSError, webbrowser.Error) as exc:
            messagebox.showerror(APP_TITLE, f'无法打开管理后台：{exc}')

    # ---- 设置 ----
    def _page_settings(self):
        self._page_heading('设置', '主题、目录与自动维护。')
        c = self.theme.c
        # 主题
        row1 = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        row1.pack(fill='x', pady=6)
        ui_theme.glass_label(row1, self.theme, '外观主题', font=(ui_theme.FONT, 10, 'bold'),
                              width=14, anchor='w').pack(side='left', padx=16, pady=14)
        ui_theme.glass_label(row1, self.theme, '跟随系统' if self.theme.mode == 'dark' else '浅色',
                              muted=True).pack(side='left', padx=6)
        ttk.Button(row1, text='切换 暗/亮', command=self.toggle_theme).pack(side='right', padx=10, pady=8)
        # 运行目录
        row2 = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        row2.pack(fill='x', pady=6)
        ui_theme.glass_label(row2, self.theme, '运行目录', font=(ui_theme.FONT, 10, 'bold'),
                              width=14, anchor='w').pack(side='left', padx=16, pady=14)
        ui_theme.glass_label(row2, self.theme, str(self.root_dir), muted=True,
                              font=(ui_theme.FONT, 9)).pack(side='left', padx=6)
        ttk.Button(row2, text='打开目录', command=lambda: os.startfile(str(self.root_dir))).pack(side='right', padx=10, pady=8)
        # 自动维护
        row3 = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        row3.pack(fill='x', pady=6)
        ui_theme.glass_label(row3, self.theme, '自动维护', font=(ui_theme.FONT, 10, 'bold'),
                              width=14, anchor='w').pack(side='left', padx=16, pady=14)
        ui_theme.glass_label(row3, self.theme, '登录自动挂载 + 每 3 分钟健康检查',
                              muted=True).pack(side='left', padx=6)
        ttk.Button(row3, text='安装', command=self._install_tasks).pack(side='right', padx=10, pady=8)

    def _install_tasks(self):
        try:
            request_task_install(self.root_dir)
            messagebox.showinfo(APP_TITLE, '自动维护任务安装完成。')
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f'登录自动启动失败: {exc}')

    # ---- 日志 ----
    def _page_logs(self):
        self._page_heading('日志', '查看引擎日志与各挂载日志。')
        log_path = self.root_dir / 'logs' / 'engine.log'
        text = ''
        if log_path.exists():
            try:
                text = log_path.read_text(encoding='utf-8', errors='replace')[-8000:]
            except OSError:
                text = ''
        if not text:
            text = '暂无日志。'
        c = self.theme.c
        box_frame = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        box_frame.pack(fill='both', expand=True)
        box = tk.Text(box_frame, bg=c['field'], fg=c['text'], insertbackground=c['text'],
                      selectbackground=c['accent'], selectforeground=c['accent_fg'],
                      relief='flat', bd=0, highlightthickness=0,
                      font=('Consolas', 9), padx=12, pady=10)
        box.pack(fill='both', expand=True, padx=1, pady=1)
        box.insert('end', text)
        box.configure(state='disabled')
        ttk.Button(self.content, text='刷新', command=self._render_page).pack(anchor='e', pady=(8, 0))

    # ---- 关于 ----
    def _about_asset(self, name):
        """返回打包资源路径；开发运行和 PyInstaller 路径均兼容。"""
        candidates = [
            bundled_root() / 'assets' / name,
            Path(__file__).resolve().parent / 'payload' / 'source' / 'assets' / name,
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def _open_project_link(self):
        self._open_webview(PROJECT_GITHUB, 'GitHub 项目主页')

    def _open_donation_image(self, path):
        if not path.exists():
            messagebox.showwarning(APP_TITLE, f'捐赠图片资源不存在：{path}', parent=self)
            return
        try:
            if os.name == 'nt':
                os.startfile(str(path))
            elif not webbrowser.open(path.as_uri(), new=2):
                raise OSError('默认图片查看器未接受打开请求')
        except (OSError, webbrowser.Error) as exc:
            messagebox.showerror(APP_TITLE, f'无法打开捐赠图片：{exc}', parent=self)

    def _page_about(self):
        # 关于页内容较长，使用独立滚动容器兼容小屏和窗口缩放。
        content_host = self.content
        scroll_host = tk.Frame(content_host, bg=self.theme.c['surface'], bd=0, highlightthickness=0)
        scroll_host.pack(fill='both', expand=True)
        canvas = tk.Canvas(scroll_host, bg=self.theme.c['surface'], bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        body = ttk.Frame(canvas, style='Surface.TFrame')
        window_id = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')), add='+')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window_id, width=event.width), add='+')
        canvas.bind('<MouseWheel>', lambda event: canvas.yview_scroll(int(-event.delta / 120), 'units'), add='+')
        self.content = body
        self._page_heading('关于', '感谢每一位使用、反馈和支持云盘挂载向导的朋友。')

        intro = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        intro.pack(fill='x', pady=(0, 10))
        ui_theme.glass_label(intro, self.theme, APP_TITLE,
                              font=(ui_theme.FONT, 15, 'bold')).pack(anchor='w', padx=18, pady=(16, 3))
        ui_theme.glass_label(
            intro, self.theme,
            f'版本 {APP_VERSION}  ·  由 {PROJECT_AUTHOR} 开发',
            muted=True,
        ).pack(anchor='w', padx=18, pady=(0, 14))
        link = ui_theme.glass_label(intro, self.theme, PROJECT_GITHUB,
                                    fg=self.theme.c['accent'], cursor='hand2',
                                    font=(ui_theme.FONT, 10, 'underline'))
        link.pack(anchor='w', padx=18, pady=(0, 16))
        link.bind('<Button-1>', lambda _event: self._open_project_link(), add='+')

        thanks = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        thanks.pack(fill='x', pady=6)
        ui_theme.glass_label(thanks, self.theme, '开源项目与致谢',
                              font=(ui_theme.FONT, 11, 'bold')).pack(anchor='w', padx=18, pady=(14, 5))
        ui_theme.glass_label(
            thanks, self.theme,
            '本项目使用并感谢以下开源项目：Alist、rclone、WinFsp、PyInstaller、Python、Tkinter、pywinstyles 以及 Pillow。感谢所有开源项目的维护者和贡献者。',
            muted=True, wraplength=720, justify='left',
        ).pack(anchor='w', padx=18, pady=(0, 14))

        donation = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        donation.pack(fill='x', pady=6)
        ui_theme.glass_label(donation, self.theme, '支持项目',
                              font=(ui_theme.FONT, 11, 'bold')).pack(anchor='w', padx=18, pady=(14, 2))
        ui_theme.glass_label(donation, self.theme, '您的赞助是我更新的动力！',
                              fg=self.theme.c['accent'], font=(ui_theme.FONT, 10, 'bold')).pack(anchor='w', padx=18, pady=(0, 10))

        qr_row = tk.Frame(donation, bg=self.theme.c['surface2'], bd=0, highlightthickness=0)
        qr_row.pack(fill='x', padx=12, pady=(0, 14))
        self._about_images = []
        for title, filename in (('微信支付', 'wechat_donation.png'), ('支付宝', 'alipay_donation.png')):
            cell = ui_theme.glass_frame(qr_row, self.theme, elevated=False)
            cell.pack(side='left', fill='both', expand=True, padx=6, pady=4)
            ui_theme.glass_label(cell, self.theme, title,
                                  font=(ui_theme.FONT, 10, 'bold')).pack(pady=(10, 5))
            path = self._about_asset(filename)
            if path.exists():
                try:
                    # Tk 原生 PhotoImage 按整数采样缩小，避免为两张静态图片引入 Pillow 大型依赖。
                    source_image = tk.PhotoImage(file=str(path))
                    scale = max(1, (source_image.width() + 189) // 190,
                                (source_image.height() + 239) // 240)
                    photo = source_image.subsample(scale, scale)
                    self._about_images.append((source_image, photo))
                    image_label = tk.Label(cell, image=photo, bg=self.theme.c['surface2'],
                                           cursor='hand2', bd=0, highlightthickness=0)
                    image_label.pack(pady=(0, 5))
                    image_label.bind('<Button-1>', lambda _event, p=path: self._open_donation_image(p), add='+')
                except Exception as exc:
                    ui_theme.glass_label(cell, self.theme, f'图片加载失败：{exc}', muted=True).pack(pady=12)
            else:
                ui_theme.glass_label(cell, self.theme, '图片资源未找到', muted=True).pack(pady=12)
            ui_theme.glass_label(cell, self.theme, '点击图片查看原图', muted=True,
                                  font=(ui_theme.FONT, 9)).pack(pady=(0, 10))

        notice = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        notice.pack(fill='x', pady=6)
        ui_theme.glass_label(notice, self.theme, '隐私声明与免责声明',
                              font=(ui_theme.FONT, 11, 'bold')).pack(anchor='w', padx=18, pady=(14, 5))
        ui_theme.glass_label(
            notice, self.theme,
            '本程序仅供个人学习、研究和技术交流使用。请遵守相关法律法规、服务条款和开源项目许可证，不要使用本程序访问、传播或处理未经授权的数据。除实现功能所必需的本地配置和运行日志外，本项目不会主动收集、出售或共享您的个人信息；请妥善保管网盘账号、密码、令牌和配置文件。',
            muted=True, wraplength=720, justify='left',
        ).pack(anchor='w', padx=18, pady=(0, 14))

    def refresh_theme(self):
        self._render_page()
        c = self.theme.c
        self.theme_btn.configure(
            text='切换到浅色' if self.theme.mode == 'dark' else '切换到深色',
            bg=c['surface'], fg=c['muted'],
            activebackground=c['surface2'], activeforeground=c['text'],
            disabledforeground=c['muted'],
        )
        self.nav.configure(bg=c['surface'], highlightbackground=c['border'])
        self.nav_title.configure(bg=c['surface'], fg=c['text'])
        self.nav_subtitle.configure(bg=c['surface'], fg=c['muted'])
        self._update_nav()

    def _poll(self):
        def on_log(t):
            status = getattr(self, 'operation_status', None)
            if status is not None and status.winfo_exists():
                status.configure(text=str(t))
        def on_done(p):
            self._operation_done(p)
        def on_error(p):
            self._show_async_error(p)
        self.poll_events(on_log, on_done, on_error)


# ==================== 挂载方案编辑对话框 ====================

class MountDialog(tk.Toplevel):
    """挂载方案增/改对话框。"""

    def __init__(self, parent, item, theme):
        super().__init__(parent)
        self.theme = theme
        self.result = None
        self.title('新建挂载方案' if not item.name else '编辑挂载方案')
        self.configure(bg=theme.c['bg'])
        self.geometry('520x560')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        self.theme.apply_glass(self)
        self._build(item)

    def _build(self, item):
        c = self.theme.c
        form = ttk.Frame(self, style='Surface.TFrame')
        form.pack(fill='both', expand=True, padx=24, pady=24)

        fields = []
        self.name_var = tk.StringVar(value=item.name)
        self.type_var = tk.StringVar(value=item.type or 'WebDAV')
        self.url_var = tk.StringVar(value=item.url or 'http://127.0.0.1:5244')
        self.user_var = tk.StringVar(value=item.user or 'admin')
        self.pass_var = tk.StringVar(value='')
        self.drive_var = tk.StringVar(value=item.drive or 'Y')
        self.path_var = tk.StringVar(value=item.path)
        self.enabled_var = tk.BooleanVar(value=item.enabled)

        rows = [
            ('方案名称', lambda: ttk.Entry(form, textvariable=self.name_var, width=40)),
            ('网盘类型', lambda: ttk.Combobox(form, textvariable=self.type_var, state='readonly', width=37,
                                            values=['WebDAV', 'Alist / OpenList', '其他（先在 Alist 后台添加）'])),
            ('服务地址', lambda: ttk.Entry(form, textvariable=self.url_var, width=40)),
            ('账号', lambda: ttk.Entry(form, textvariable=self.user_var, width=40)),
            ('密码', lambda: ttk.Entry(form, textvariable=self.pass_var, show='*', width=40)),
            ('盘符', lambda: ttk.Combobox(form, textvariable=self.drive_var, state='readonly', width=37,
                                         values=[f'{l}:' for l in available_letters()])),
            ('子路径(可选)', lambda: ttk.Entry(form, textvariable=self.path_var, width=40)),
        ]
        for i, (label, make_widget) in enumerate(rows):
            ttk.Label(form, text=label, style='Surface.TLabel', width=14).grid(row=i, column=0, sticky='w', pady=8)
            make_widget().grid(row=i, column=1, sticky='w')
        self.enabled_check = ui_theme.GlassCheckbutton(
            form,
            text='启用该方案',
            variable=self.enabled_var,
            theme=self.theme,
        )
        self.enabled_check.grid(row=len(rows), column=1, sticky='w', pady=8)

        footer = ttk.Frame(self, style='Surface.TFrame')
        footer.pack(fill='x', padx=24, pady=(0, 20))
        ttk.Button(footer, text='取消', command=self._cancel).pack(side='right')
        ttk.Button(footer, text='保存', style='Primary.TButton', command=lambda: self._save(item)).pack(side='right', padx=10)
        self.test_button = ttk.Button(footer, text='测试连接', command=lambda: self._test_connection(item))
        self.test_button.pack(side='left')

    def _test_connection(self, item):
        if getattr(self, '_testing', False):
            return
        if self.type_var.get() != 'WebDAV':
            messagebox.showinfo(APP_TITLE, '连接测试目前仅适用于 WebDAV 方案。', parent=self)
            return
        candidate = Item(
            id=item.id,
            name=self.name_var.get().strip(),
            type=self.type_var.get(),
            url=self.url_var.get().strip(),
            user=self.user_var.get().strip() or 'admin',
            passwd=item.passwd,
            drive=self.drive_var.get().rstrip(':') or 'Y',
            path=self.path_var.get().strip(),
            enabled=self.enabled_var.get(),
        )
        if self.pass_var.get():
            try:
                candidate.passwd = obscure(runtime_root(), self.pass_var.get())
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f'加密密码失败：{exc}', parent=self)
                return
        try:
            validate_mount_item(candidate)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return

        self._testing = True
        self.test_button.configure(text='测试中…', state='disabled')

        def worker():
            try:
                ok, error = remote_probe(runtime_root(), candidate)
            except Exception as exc:
                ok, error = False, str(exc)
            def finish():
                if not self.winfo_exists():
                    return
                self._testing = False
                self.test_button.configure(text='测试连接', state='normal')
                if ok:
                    messagebox.showinfo(APP_TITLE, 'WebDAV 连接成功，服务地址和凭据可用。', parent=self)
                else:
                    detail = str(error).strip()
                    messagebox.showerror(APP_TITLE, f'WebDAV 连接失败：{detail or "无法访问服务"}', parent=self)
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _cancel(self):
        self.result = None
        self.destroy()

    def _save(self, item):
        if not self.name_var.get().strip():
            messagebox.showerror(APP_TITLE, '请输入方案名称')
            return
        if not self.url_var.get().strip():
            messagebox.showerror(APP_TITLE, '请输入服务地址')
            return
        passwd = item.passwd
        if self.pass_var.get():
            try:
                passwd = obscure(runtime_root(), self.pass_var.get())
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f'加密密码失败：{exc}')
                return
        candidate = Item(
            id=item.id,
            name=self.name_var.get().strip(),
            type=self.type_var.get(),
            url=self.url_var.get().strip(),
            user=self.user_var.get().strip() or 'admin',
            passwd=passwd,
            drive=self.drive_var.get().rstrip(':') or 'Y',
            path=self.path_var.get().strip(),
            enabled=self.enabled_var.get(),
        )
        try:
            self.result = validate_mount_item(candidate)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        self.destroy()


# ==================== main ====================

def main():
    root = prepare_runtime()
    if '--install-tasks' in sys.argv:
        result_arg = '--result'
        try:
            result_path = sys.argv[sys.argv.index(result_arg) + 1]
        except (ValueError, IndexError):
            raise SystemExit('缺少 --result 参数')
        try:
            if not is_admin():
                raise RuntimeError('管理员权限未生效')
            install_scheduled_tasks(root)
            write_task_result(result_path, True, '自动维护任务安装完成')
        except Exception as exc:
            write_task_result(result_path, False, str(exc))
        raise SystemExit(0 if is_admin() else 1)
    if '--health' in sys.argv:
        raise SystemExit(0 if health_check(root) is None else 1)
    if '--prepare-runtime' in sys.argv:
        # 安装器只需要释放工具文件，不能在安装阶段启动服务或挂载盘符。
        tools = root / 'tools'
        if not (tools / 'alist.exe').exists() or not (tools / 'rclone.exe').exists():
            raise SystemExit('运行目录工具释放不完整')
        raise SystemExit(0)
    if '--startup' in sys.argv:
        try:
            startup(root)
        except Exception as exc:
            append_engine_log(root, f'登录自动启动失败: {exc}')
        raise SystemExit(0)
    if '--mount-all' in sys.argv:
        try:
            mount_all(root, append_engine_log)
        except Exception as exc:
            append_engine_log(root, f'自动挂载失败: {exc}')
        raise SystemExit(0)

    # 首次配置走鱼骨向导，已配置直接进控制台
    if is_configured(root):
        Console(root).mainloop()
    else:
        SetupWizard(root).mainloop()


if __name__ == '__main__':
    main()
