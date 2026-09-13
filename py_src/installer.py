"""云盘挂载向导 · 一键安装程序

将 mount_wizard.exe 与 WinFsp 驱动捆绑为单个分发文件：
- 释放主程序到 Program Files
- 静默安装 WinFsp（未安装时）
- 释放 Alist / rclone 到 runtime/tools（随主程序初始化）
- 配置 runtime 目录权限
- 创建桌面/开始菜单快捷方式
- 注册控制面板卸载项
- 升级场景自动把旧计划任务指向新程序
"""
import ctypes
from ctypes import wintypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ui_theme
from ui_theme import Theme

APP_TITLE = '云盘挂载向导 · 安装程序'
APP_NAME = '云盘挂载向导'
VERSION = '1.0.0'
DEFAULT_DIR = r'C:\Program Files\mount'
TASK_MOUNT = 'CloudDriveMount'
TASK_HEALTH = 'CloudDriveHealth'
UNINST_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CloudDriveMountWizard'
LNK_NAME = '云盘挂载向导.lnk'


def frozen():
    return bool(getattr(sys, 'frozen', False))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def hidden_kwargs():
    kwargs = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs['startupinfo'] = startup
    return kwargs


def winfsp_installed():
    import winreg
    for sub in (r'SOFTWARE\WinFsp', r'SOFTWARE\WOW6432Node\WinFsp'):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub):
                return True
        except OSError:
            continue
    return False


def common_desktop():
    return Path(os.environ.get('PUBLIC', r'C:\Users\Public')) / 'Desktop'


def start_menu():
    return Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'


def schtasks_exists(name):
    result = subprocess.run(['schtasks.exe', '/Query', '/TN', name], capture_output=True, **hidden_kwargs())
    return result.returncode == 0


def _powershell_encoded(command):
    import base64
    return base64.b64encode(command.encode('utf-16le')).decode('ascii')


def make_shortcut(lnk_path, exe_path, workdir):
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        "$s = $ws.CreateShortcut($env:CM_LINK);"
        "$s.TargetPath = $env:CM_TARGET;"
        "$s.WorkingDirectory = $env:CM_WORKDIR;"
        "$s.Description = $env:CM_DESC;"
        "$s.IconLocation = $env:CM_TARGET + ',0';"
        "$s.Save()"
    )
    env = os.environ.copy()
    env.update({
        'CM_LINK': str(Path(lnk_path).resolve()),
        'CM_TARGET': str(Path(exe_path).resolve()),
        'CM_WORKDIR': str(Path(workdir).resolve()),
        'CM_DESC': APP_NAME,
    })
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-EncodedCommand', _powershell_encoded(ps)],
        capture_output=True, timeout=60, env=env, **hidden_kwargs()
    )
    if result.returncode != 0 or not Path(lnk_path).exists():
        raise RuntimeError(f'创建快捷方式失败：{lnk_path}')


def _protected_paths():
    values = [Path.home()]
    for key in ('USERPROFILE', 'WINDIR', 'SystemRoot', 'ProgramData', 'PUBLIC'):
        value = os.environ.get(key)
        if value:
            values.append(Path(value))
    for key in ('Desktop', 'Downloads', 'Documents'):
        value = os.environ.get(key)
        if value:
            values.append(Path(value))
    return {path.resolve() for path in values}


def validate_target(target, for_uninstall=False):
    target = Path(target).expanduser().resolve()
    if not target.name or target == Path(target.anchor):
        raise ValueError(f'安装目录不能是磁盘根目录：{target}')
    if target in _protected_paths():
        raise ValueError(f'禁止使用受保护目录：{target}')
    markers = ('mount_wizard.exe', 'uninstall.exe', 'CloudMountSetup.exe')
    if for_uninstall:
        if not any((target / marker).exists() for marker in markers):
            raise ValueError(f'目录不是云盘挂载向导安装目录，拒绝卸载：{target}')
    elif target.exists() and any(target.iterdir()):
        if not any((target / marker).exists() for marker in markers):
            raise ValueError(f'目标目录非空且不是本程序目录，拒绝覆盖：{target}')
    return target


def write_uninstall_registry(target):
    import winreg
    total = 0
    for item in (
        target / 'mount_wizard.exe',
        target / 'CloudMountSetup.exe',
        target / 'uninstall.exe',
        target / 'THIRD_PARTY_NOTICES.txt',
        target / 'runtime',
    ):
        try:
            if item.is_file():
                total += item.stat().st_size
            elif item.is_dir():
                for file in item.rglob('*'):
                    if file.is_file():
                        total += file.stat().st_size
        except OSError:
            continue
    size_kb = total // 1024
    uninstaller = target / 'uninstall.exe'
    values = {
        'DisplayName': APP_NAME,
        'DisplayVersion': VERSION,
        'Publisher': 'CloudMount Tools',
        'InstallLocation': str(target),
        'DisplayIcon': str(target / 'mount_wizard.exe') + ',0',
        'UninstallString': f'"{uninstaller}"',
        'EstimatedSize': size_kb,
    }
    key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINST_KEY)
    try:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
        winreg.SetValueEx(key, 'EstimatedSize', 0, winreg.REG_DWORD, int(size_kb))
        winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'NoRepair', 0, winreg.REG_DWORD, 1)
    finally:
        winreg.CloseKey(key)


def delete_uninstall_registry():
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINST_KEY)
    except OSError:
        pass


def delayed_cleanup(setup_path, remove_dir=False):
    ps = '$ErrorActionPreference = "SilentlyContinue"; Start-Sleep -Seconds 3; Remove-Item -LiteralPath $env:CM_SETUP -Force'
    if remove_dir:
        ps += '; Remove-Item -LiteralPath $env:CM_PARENT -Recurse -Force'
    env = os.environ.copy()
    env['CM_SETUP'] = str(Path(setup_path).resolve())
    env['CM_PARENT'] = str(Path(setup_path).resolve().parent)
    subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-EncodedCommand', _powershell_encoded(ps)],
        env=env, **hidden_kwargs()
    )


def do_install(target, emit, progress):
    target = validate_target(target, for_uninstall=False)
    steps_total = 8

    emit('正在检查运行中的程序…')
    subprocess.run(['taskkill.exe', '/IM', 'mount_wizard.exe', '/F'], capture_output=True, **hidden_kwargs())
    time.sleep(0.6)
    progress(1 / steps_total)

    emit('正在创建安装目录…')
    target.mkdir(parents=True, exist_ok=True)
    for sub in ('runtime', 'runtime/logs'):
        (target / sub).mkdir(parents=True, exist_ok=True)
    progress(2 / steps_total)

    emit('正在释放程序文件（约 85MB，请稍候）…')
    payload = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'payload'
    wizard_src = payload / 'mount_wizard.exe'
    if not wizard_src.exists():
        raise RuntimeError('安装包损坏：缺少主程序文件')
    staged = target / 'mount_wizard.exe'
    tmp = target / 'mount_wizard.exe.new'
    shutil.copyfile(wizard_src, tmp)
    os.replace(tmp, staged)

    notices = payload / 'THIRD_PARTY_NOTICES.txt'
    if notices.exists():
        shutil.copyfile(notices, target / 'THIRD_PARTY_NOTICES.txt')

    # 同时把 WinFsp MSI 复制到安装目录，供 mount_wizard 后续按需重新安装 WinFsp
    wpfsp_msi_src = payload / 'winfsp.msi'
    if wpfsp_msi_src.exists():
        (target / 'tools').mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wpfsp_msi_src, target / 'tools' / 'winfsp.msi')

    # 释放独立的卸载程序 uninstall.exe（双击即卸载，无需参数）
    uninstaller_src = payload / 'uninstall.exe'
    if uninstaller_src.exists():
        shutil.copyfile(uninstaller_src, target / 'uninstall.exe')

    setup_copy = target / 'CloudMountSetup.exe'
    self_path = Path(sys.executable).resolve() if frozen() else Path(__file__).resolve()
    if self_path.suffix.lower() == '.exe' and self_path != setup_copy:
        shutil.copyfile(self_path, setup_copy)
    progress(3 / steps_total)

    winfsp_newly = False
    if winfsp_installed():
        emit('WinFsp 驱动已安装，跳过。')
    else:
        emit('正在静默安装 WinFsp 驱动（1-2 分钟）…')
        msi = payload / 'winfsp.msi'
        if not msi.exists():
            raise RuntimeError('安装包损坏：缺少 winfsp.msi')
        log = target / 'runtime' / 'logs' / 'winfsp-install.log'
        result = subprocess.run(
            ['msiexec.exe', '/i', str(msi), '/qn', '/norestart', '/L*v', str(log)],
            capture_output=True, timeout=600, **hidden_kwargs()
        )
        if result.returncode != 0 and not winfsp_installed():
            raise RuntimeError(f'WinFsp 安装失败（代码 {result.returncode}），日志：{log}')
        winfsp_newly = True
        emit('WinFsp 驱动安装完成。')
    progress(4 / steps_total)

    emit('正在配置运行目录权限…')
    acl_result = subprocess.run(
        ['icacls.exe', str(target / 'runtime'), '/grant', 'Users:(OI)(CI)M'],
        capture_output=True, **hidden_kwargs()
    )
    if acl_result.returncode != 0:
        raise RuntimeError('运行目录权限配置失败')
    progress(5 / steps_total)

    emit('正在初始化 Alist / rclone 驱动文件…')
    exe = target / 'mount_wizard.exe'
    runtime_tools = target / 'runtime' / 'tools'
    if runtime_tools.exists():
        # 强制删除残留（空目录或部分文件），保证 prepare_runtime 重新完整复制
        try:
            shutil.rmtree(runtime_tools, ignore_errors=True)
        except OSError:
            pass
    if exe.exists():
        # 只触发运行时工具释放，不能在安装阶段启动 Alist 或执行挂载。
        result = subprocess.run(
            [str(exe), '--prepare-runtime'], capture_output=True, timeout=300, **hidden_kwargs()
        )
        if result.returncode != 0 or not (runtime_tools / 'alist.exe').exists() or not (runtime_tools / 'rclone.exe').exists():
            raise RuntimeError(f'运行时工具初始化失败（代码 {result.returncode}）')

    emit('正在创建快捷方式…')
    make_shortcut(common_desktop() / LNK_NAME, exe, target)
    make_shortcut(start_menu() / LNK_NAME, exe, target)
    progress(6 / steps_total)

    emit('正在注册卸载信息…')
    write_uninstall_registry(target)
    progress(7 / steps_total)

    if schtasks_exists(TASK_MOUNT) or schtasks_exists(TASK_HEALTH):
        emit('检测到旧版自动维护任务，正在更新到新程序…')
        common = ['/RU', 'SYSTEM', '/RL', 'HIGHEST', '/F']
        commands = [
            ['schtasks.exe', '/Create', '/TN', TASK_MOUNT, '/SC', 'ONLOGON', '/TR', f'"{exe}" --startup'] + common,
            ['schtasks.exe', '/Create', '/TN', TASK_HEALTH, '/SC', 'MINUTE', '/MO', '3', '/TR', f'"{exe}" --health'] + common,
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, **hidden_kwargs())
            if result.returncode != 0:
                emit(f'警告：计划任务 {command[command.index("/TN") + 1]} 更新失败，可稍后在向导中重新安装。')

    progress(1.0)
    return {'reboot': winfsp_newly, 'target': str(target)}


def do_uninstall(target, keep_data, emit, progress):
    target = validate_target(target, for_uninstall=True)
    steps_total = 6

    emit('正在停止程序与挂载进程…')
    for proc in ('mount_wizard.exe', 'alist.exe', 'rclone.exe'):
        subprocess.run(['taskkill.exe', '/IM', proc, '/F', '/T'], capture_output=True, **hidden_kwargs())
    time.sleep(1.5)
    progress(1 / steps_total)

    emit('正在移除计划任务…')
    for task in (TASK_MOUNT, TASK_HEALTH):
        if not schtasks_exists(task):
            continue
        subprocess.run(['schtasks.exe', '/Delete', '/TN', task, '/F'], capture_output=True, **hidden_kwargs())
    progress(2 / steps_total)

    emit('正在移除快捷方式…')
    for path in (common_desktop() / LNK_NAME, start_menu() / LNK_NAME):
        try:
            path.unlink()
        except OSError:
            pass
    progress(3 / steps_total)

    emit('正在移除注册表信息…')
    delete_uninstall_registry()
    progress(4 / steps_total)

    emit('正在删除程序文件…')
    self_path = Path(sys.executable).resolve() if frozen() else Path(__file__).resolve()
    keep_names = {'runtime'} if keep_data else set()

    for item in (list(target.iterdir()) if target.exists() else []):
        if item.name in keep_names:
            continue
        if item == self_path:
            continue  # 正在运行的自身（CloudMountSetup.exe 或 uninstall.exe），最后延迟删除
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink()
        except OSError as exc:
            emit(f'警告：无法删除 {item.name}（{exc.strerror}）')

    # 延迟删除自身；若非保留数据，则连同整个安装目录一并删除
    delayed_cleanup(str(self_path), remove_dir=not keep_data)

    progress(1.0)
    return {'kept': keep_data}


class InstallerGUI(tk.Tk):
    def __init__(self, mode, target):
        super().__init__()
        self.mode = mode
        self.target = Path(target)
        self.events = queue.Queue()
        self.busy = False
        self.result = None
        self.keep_data = tk.BooleanVar(value=True)
        self.theme = Theme(self)
        self._style()
        self._layout()
        self.render()
        self.after(200, self.poll_events)

    def _style(self):
        c = self.theme.c
        self.title(APP_TITLE)
        self._set_initial_geometry()
        self.configure(bg=c['bg'])
        self.option_add('*Font', (ui_theme.FONT, 10))
        self.theme.apply_glass()

    def _set_initial_geometry(self):
        """使用桌面工作区设置初始窗口，确保底部操作栏不被任务栏遮挡。"""
        left = top = 0
        right = self.winfo_screenwidth()
        bottom = self.winfo_screenheight()
        if os.name == 'nt':
            try:
                work_area = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0):
                    left, top = work_area.left, work_area.top
                    right, bottom = work_area.right, work_area.bottom
            except (AttributeError, OSError):
                pass

        available_width = max(1, right - left)
        available_height = max(1, bottom - top)
        preferred_width = 820
        preferred_height = 700
        margin = 24

        # 工作区优先，极端小屏也不能让窗口越过屏幕边界。
        width = min(preferred_width, max(1, available_width - margin * 2))
        height = min(preferred_height, max(1, available_height - margin * 2))
        self.minsize(min(760, width), min(600, height))
        self.resizable(True, True)

        x = left + max(0, (available_width - width) // 2)
        y = top + max(0, (available_height - height) // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')

    def toggle_theme(self):
        self.theme.toggle()
        c = self.theme.c
        self.configure(bg=c['bg'])
        self.theme.apply_glass()
        if hasattr(self, 'theme_btn'):
            self.theme_btn.configure(text='切换到浅色' if self.theme.mode == 'dark' else '切换到深色')
        self.render()

    def _layout(self):
        header = ttk.Frame(self)
        header.pack(fill='x', padx=40, pady=(28, 14))
        top = ttk.Frame(header)
        top.pack(fill='x')
        ttk.Label(top, text=APP_TITLE, style='Title.TLabel').pack(side='left')
        self.theme_btn = ttk.Button(top,
                                    text='切换到浅色' if self.theme.mode == 'dark' else '切换到深色',
                                    style='ThemeToggle.TButton', command=self.toggle_theme)
        self.theme_btn.pack(side='right')
        self.subtitle = ttk.Label(header, text='', style='Muted.TLabel', wraplength=720, justify='left')
        self.subtitle.pack(anchor='w', pady=(6, 0))

        # 底部操作栏先分配固定空间，低分辨率下只压缩中间内容区。
        footer = ttk.Frame(self)
        footer.pack(side='bottom', fill='x', padx=40, pady=(0, 24))
        self.main_button = ttk.Button(footer, text='开始安装', style='Primary.TButton', command=self.on_main)
        self.main_button.pack(side='right')
        self.quit_button = ttk.Button(footer, text='取消', command=self.destroy)
        self.quit_button.pack(side='right', padx=(0, 10))
        self.launch_button = ttk.Button(footer, text='立即启动向导', command=self.launch_wizard)
        self.launch_button.pack(side='right')
        self.launch_button.pack_forget()

        self.card = ttk.Frame(self, style='Surface.TFrame')
        self.card.pack(fill='both', expand=True, padx=40, pady=(0, 16))
        self.content = ttk.Frame(self.card, style='Surface.TFrame')
        self.content.pack(fill='both', expand=True, padx=30, pady=26)

    def clear(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def render(self):
        self.clear()
        if self.mode == 'install':
            self.render_install()
            return
        if self.mode == 'uninstall':
            self.render_uninstall()
            return
        self.render_progress()

    def render_install(self):
        self.subtitle.configure(text='将云盘挂载向导安装到这台电脑。程序基于 Alist + rclone + WinFsp，可把多个网盘挂载为本地盘符。')
        ttk.Label(self.content, text='安装位置', style='Heading.TLabel').pack(anchor='w')
        row = ttk.Frame(self.content, style='Surface.TFrame')
        row.pack(fill='x', pady=(10, 18))
        self.dir_var = tk.StringVar(value=str(self.target))
        ttk.Entry(row, textvariable=self.dir_var, width=58).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='浏览…', command=self.browse).pack(side='left', padx=(10, 0))

        info = [
            ('主程序', '云盘挂载向导（含挂载与配置界面，约 85MB）'),
            ('WinFsp 驱动', '已安装，将跳过' if winfsp_installed() else '未安装，安装程序将自动静默安装'),
            ('Alist 网盘服务', '随主程序释放到 runtime\\tools'),
            ('rclone 挂载引擎', '随主程序释放到 runtime\\tools'),
            ('快捷方式', '桌面 + 开始菜单'),
            ('卸载支持', '控制面板「应用和功能」或开始菜单'),
        ]
        c = self.theme.c
        for title, detail in info:
            line = ui_theme.glass_frame(self.content, self.theme, elevated=True)
            line.pack(fill='x', pady=5)
            ui_theme.glass_label(line, self.theme, title, font=(ui_theme.FONT, 10, 'bold'),
                                  width=12, anchor='w').pack(side='left', padx=14, pady=11)
            ui_theme.glass_label(line, self.theme, detail, muted=True).pack(side='left', padx=4)

        ttk.Label(
            self.content,
            text='开源组件：rclone (GPLv3) · Alist (AGPLv3) · WinFsp (GPLv3, Bill Zissimopoulos)。详见安装目录中的 THIRD_PARTY_NOTICES.txt。',
            style='SurfaceMuted.TLabel', wraplength=620, justify='left'
        ).pack(anchor='w', pady=(16, 0))

        self.main_button.configure(text='开始安装', command=self.on_main, state='normal')
        self.quit_button.configure(text='取消', command=self.destroy)
        self.launch_button.pack_forget()

    def render_uninstall(self):
        self.subtitle.configure(text='从这台电脑移除云盘挂载向导。卸载会取消所有挂载并停止 Alist / rclone 进程。')
        ttk.Label(self.content, text='确认卸载', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(
            self.content,
            text='· 移除主程序、快捷方式、计划任务与注册表信息\n· 正在挂载的网盘盘符将被断开\n· 卸载完成后建议重启资源管理器以刷新「此电脑」',
            style='SurfaceMuted.TLabel', justify='left', wraplength=620
        ).pack(anchor='w', pady=(10, 16))
        self.keep_data_check = ui_theme.GlassCheckbutton(
            self.content,
            text='保留挂载配置与 Alist 数据（runtime 目录）',
            variable=self.keep_data,
            theme=self.theme,
        )
        self.keep_data_check.pack(anchor='w', pady=(2, 0))
        self.main_button.configure(text='开始卸载', style='Danger.TButton', command=self.on_main, state='normal')
        self.quit_button.configure(text='取消', command=self.destroy)
        self.launch_button.pack_forget()

    def render_progress(self):
        self.subtitle.configure(text='请稍候，正在执行…')
        ttk.Label(self.content, text='执行进度', style='Heading.TLabel').pack(anchor='w')
        self.progress_bar = ttk.Progressbar(self.content, maximum=100, value=0)
        self.progress_bar.pack(fill='x', pady=(12, 14))
        output_frame = ui_theme.glass_frame(self.content, self.theme, elevated=True)
        output_frame.pack(fill='both', expand=True)
        self.output = tk.Text(output_frame, height=12, bg=self.theme.c['field'], fg=self.theme.c['text'],
                              insertbackground=self.theme.c['text'], selectbackground=self.theme.c['accent'],
                              selectforeground=self.theme.c['accent_fg'], relief='flat', bd=0,
                              highlightthickness=0, padx=12, pady=10, font=('Consolas', 9))
        self.output.pack(fill='both', expand=True, padx=1, pady=1)
        self.output.insert('end', '准备就绪。')
        self.output.configure(state='disabled')
        self.main_button.configure(state='disabled')
        self.quit_button.configure(state='disabled')

    def render_done(self, summary):
        self.subtitle.configure(text='操作已完成。')
        ttk.Label(self.content, text='完成', style='Heading.TLabel').pack(anchor='w')
        lines = []
        if self.mode.startswith('install'):
            lines.append(f"安装位置：{summary.get('target', self.target)}")
            if summary.get('reboot'):
                lines.append('WinFsp 驱动为本次新安装：建议重启电脑后再使用挂载功能（驱动需重启后完全生效）。')
            else:
                lines.append('所有组件就绪：双击桌面「云盘挂载向导」即可开始。')
            lines.append('首次使用：启动向导 → 配置 Alist → 添加挂载方案。如需开机自动挂载，请在向导最后一步点击「安装自动维护」。')
            color = self.theme.c['warning'] if summary.get('reboot') else self.theme.c['success']
        else:
            lines.append('卸载完成。')
            if summary.get('kept'):
                lines.append('挂载配置与 Alist 数据已保留在 runtime 目录，重新安装后可继续使用。')
            lines.append('若「此电脑」中仍残留云盘盘符，请重启资源管理器或重启电脑。')
            color = self.theme.c['success']

        for line in lines:
            ttk.Label(self.content, text=line, style='SurfaceMuted.TLabel', wraplength=620, justify='left').pack(anchor='w', pady=4)

        self.progress_bar.configure(value=100)
        self.progress_bar.pack_forget()
        self.output.pack_forget()
        self.main_button.configure(text='完成', command=self.destroy, state='normal')
        self.quit_button.pack_forget()
        if self.mode.startswith('install'):
            self.launch_button.pack(side='right')

    def browse(self):
        chosen = filedialog.askdirectory(initialdir=str(self.target), parent=self)
        if chosen:
            self.dir_var.set(chosen)
            self.target = Path(chosen)

    def on_main(self):
        if self.busy:
            return
        if self.mode.startswith('install'):
            if hasattr(self, 'dir_var'):
                self.target = Path(self.dir_var.get().strip() or DEFAULT_DIR)
            action = do_install
        else:
            action = lambda target, emit, progress: do_uninstall(target, self.keep_data.get(), emit, progress)
        self.run_async(action)

    def run_async(self, action):
        if not is_admin():
            messagebox.showerror(APP_TITLE, '需要管理员权限：请右键以管理员身份运行本安装程序。')
            return
        self.busy = True
        self.mode = self.mode + ':run' if ':' not in self.mode else self.mode
        self.render()

        def worker():
            emit = lambda text: self.events.put(('log', text))
            progress = lambda value: self.events.put(('progress', value))
            try:
                result = action(self.target, emit, progress)
                self.events.put(('done', result))
            except Exception as exc:
                self.events.put(('error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'log':
                    self.write_output(payload)
                elif kind == 'progress':
                    if hasattr(self, 'progress_bar'):
                        self.progress_bar.configure(value=float(payload) * 100)
                elif kind == 'done':
                    self.busy = False
                    self.result = payload
                    self.write_output('—— 操作成功完成 ——')
                    self.render_done(payload)
                else:
                    self.busy = False
                    self.write_output(f'—— 执行失败 ——\n{payload}')
                    if hasattr(self, 'progress_bar'):
                        self.progress_bar.configure(value=0)
                    self.main_button.configure(text='重试', state='normal', command=self.on_main)
                    self.quit_button.configure(text='退出', state='normal', command=self.destroy)
                    messagebox.showerror(APP_TITLE, str(payload))
        except queue.Empty:
            pass
        self.after(200, self.poll_events)

    def write_output(self, text):
        if not hasattr(self, 'output') or not self.output.winfo_exists():
            return
        self.output.configure(state='normal')
        self.output.insert('end', '\n' + str(text))
        self.output.see('end')
        self.output.configure(state='disabled')

    def launch_wizard(self):
        exe = self.target / 'mount_wizard.exe'
        if exe.exists():
            subprocess.Popen([str(exe)], cwd=str(self.target))


def run_silent(mode, target):
    """静默模式：无界面执行，结果写日志文件并影响退出码。"""
    log_path = Path(os.environ.get('TEMP', '.')) / 'CloudMountSetup_silent.log'

    def log(text):
        with log_path.open('a', encoding='utf-8') as handle:
            handle.write(time.strftime('%H:%M:%S ') + text + '\n')
        print(text, flush=True)

    if not is_admin():
        log('错误：需要管理员权限。')
        return 1

    log_path.write_text('', encoding='utf-8')
    try:
        if mode == 'uninstall':
            do_uninstall(target, False, log, lambda _v: None)
            log('卸载完成。')
        else:
            summary = do_install(target, log, lambda _v: None)
            log('安装完成。' + ('（WinFsp 新安装，建议重启）' if summary.get('reboot') else ''))
        return 0
    except Exception as exc:
        log(f'失败：{exc}')
        return 1


def elevate_relaunch(extra_args):
    """以管理员身份重新启动自身。"""
    params = subprocess.list2cmdline(extra_args)
    code = ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', str(Path(sys.executable).resolve()), params, None, 1
    )
    return code > 32


def main():
    argv = sys.argv[1:]
    silent = '--silent' in argv
    uninstall = '--uninstall' in argv
    target = DEFAULT_DIR
    if '--dir' in argv:
        try:
            target = argv[argv.index('--dir') + 1]
        except IndexError:
            pass

    if not is_admin():
        extra = []
        if uninstall:
            extra.append('--uninstall')
        if silent:
            extra.append('--silent')
        extra.extend(['--dir', target])
        if frozen() and elevate_relaunch(extra):
            raise SystemExit(0)
        print('需要管理员权限：请右键以管理员身份运行。')
        raise SystemExit(1)

    if silent:
        raise SystemExit(run_silent('uninstall' if uninstall else 'install', Path(target)))

    gui = InstallerGUI('uninstall' if uninstall else 'install', Path(target))
    gui.mainloop()


if __name__ == '__main__':
    main()
