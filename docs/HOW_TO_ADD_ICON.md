# 如何为安装包添加图标

当前安装包和主程序 CloudMount.exe 复制到桌面后显示为空白图标，是因为 NSIS 编译时没有内置图标。

## 解决方案

已在 `installer.nsi` 和 `launcher.nsi` 中添加了图标支持代码。现在只需要准备一个图标文件：

### 步骤 1：准备图标文件

**选项 A - 使用在线工具制作**：
1. 访问 https://www.icoconvert.com/ 或 https://favicon.io/
2. 上传一张云盘或磁盘主题的 PNG/JPG 图片（推荐尺寸 256x256）
3. 转换为 .ico 格式并下载

**选项 B - 使用系统图标**：
复制 Windows 系统图标（如磁盘驱动器图标）：
```powershell
# 从 imageres.dll 提取磁盘图标（需要第三方工具如 ResourceHacker）
```

**选项 C - 下载现成图标**：
从图标网站下载：
- iconfinder.com
- flaticon.com
- icons8.com

搜索关键词：cloud drive, network drive, mount, disk

### 步骤 2：放置图标

将图标文件重命名为 `icon.ico`，放到：
```
C:\Users\22303\Desktop\winmount\source\icon.ico
```

### 步骤 3：重新构建

在项目根目录运行：
```powershell
.\build.ps1
```

构建完成后，`dist\CloudMountSetup.exe` 和安装后的 `CloudMount.exe` 都会有图标。

---

## 已修改的文件

- `source\installer.nsi`：添加了 `Icon "icon.ico"` 和 `UninstallIcon "icon.ico"`
- `source\launcher.nsi`：添加了 `Icon "icon.ico"`

如果 `icon.ico` 不存在，编译器会自动跳过图标设置（不会报错）。

## 验证

重新构建并复制到桌面后，图标应该正常显示而不是空白页。
