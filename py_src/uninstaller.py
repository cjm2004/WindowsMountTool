"""云盘挂载向导 · 卸载程序

独立的卸载 exe（uninstall.exe）。放在安装目录下，双击即进入卸载界面，
无需任何参数。卸载目标 = 本 exe 所在目录。
"""
import os
import sys
import time
from pathlib import Path

from installer import (
    APP_TITLE,
    InstallerGUI,
    do_uninstall,
    elevate_relaunch,
    frozen,
    is_admin,
)


def main():
    argv = sys.argv[1:]
    silent = '--silent' in argv

    # 卸载目标 = 本 exe 所在目录（uninstall.exe 由安装器释放到安装目录）
    if frozen():
        target = Path(sys.executable).resolve().parent
    else:
        target = Path(__file__).resolve().parent

    if not is_admin():
        extra = ['--silent'] if silent else []
        if frozen() and elevate_relaunch(extra):
            raise SystemExit(0)
        print('需要管理员权限：请右键以管理员身份运行。')
        raise SystemExit(1)

    if silent:
        log_path = Path(os.environ.get('TEMP', '.')) / 'CloudMountSetup_silent.log'

        def log(text):
            with log_path.open('a', encoding='utf-8') as handle:
                handle.write(time.strftime('%H:%M:%S ') + text + '\n')
            print(text, flush=True)

        try:
            do_uninstall(target, False, log, lambda _v: None)
            log('卸载完成。')
        except Exception as exc:
            log(f'失败：{exc}')
            raise SystemExit(1)
        raise SystemExit(0)

    gui = InstallerGUI('uninstall', target)
    gui.mainloop()


if __name__ == '__main__':
    main()
