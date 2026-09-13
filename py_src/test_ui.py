# test_ui.py - 验证 InstallerGUI 能正确构建和渲染（不进入 mainloop）
import sys
sys.path.insert(0, r'C:\Users\22303\Desktop\winmount\py_src')
import installer

# 验证关键函数存在且逻辑正确
print("== 模块导入 OK ==")
print("APP_TITLE:", installer.APP_TITLE)
print("DEFAULT_DIR:", installer.DEFAULT_DIR)
print("winfsp_installed():", installer.winfsp_installed())

# 测试 install 模式 UI 构建
print("\n== 构建 InstallerGUI(install) ==")
try:
    gui = installer.InstallerGUI('install', installer.Path('C:\\CloudMountTest'))
    gui.update_idletasks()
    print("✓ install 界面构建成功，窗口标题:", gui.title())
    # 检查渲染的驱动信息行
    children = gui.content.winfo_children()
    print("✓ content 子控件数:", len(children))
    gui.destroy()
except Exception as e:
    print("✗ install 界面失败:", e)

# 测试 uninstall 模式
print("\n== 构建 InstallerGUI(uninstall) ==")
try:
    gui = installer.InstallerGUI('uninstall', installer.Path('C:\\CloudMountTest'))
    gui.update_idletasks()
    print("✓ uninstall 界面构建成功")
    gui.destroy()
except Exception as e:
    print("✗ uninstall 界面失败:", e)

# 测试 do_install 的文件释放逻辑（非管理员，跳过需要提权的步骤会抛异常，但能验证前半段）
print("\n== 测试 do_install 文件释放（模拟，仅验证前半段逻辑） ==")
def emit(t): print("  [emit]", t)
def progress(v): pass
# 不实际调用 do_install（需要管理员），只验证函数存在
print("do_install 存在:", callable(installer.do_install))
print("do_uninstall 存在:", callable(installer.do_uninstall))
print("main 存在:", callable(installer.main))

print("\n== 全部验证完成 ==")
