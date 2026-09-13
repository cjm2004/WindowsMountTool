# NSIS 图标问题 - 事后手动替换方案

经过多次尝试（PNG 格式 ICO → 8-bit BMP ICO → 相对路径 → 绝对路径），NSIS 3.12 始终无法在编译时加载 icon.ico，产物仍显示默认 NSIS 图标。

## 根本原因分析

NSIS 3.12 的 Icon 指令对文件格式、路径、编译环境都有严格要求，且错误时不报错只是静默跳过。可能的原因：
1. NSIS 编译器版本与 ICO 格式的兼容性问题
2. 编译时工作目录路径解析问题
3. NSIS 对 ICO 文件内部结构的特殊要求

## 推荐解决方案：Resource Hacker 手动替换

**步骤**：

1. **下载 Resource Hacker**
   - 官网：http://www.angusj.com/resourcehacker/
   - 或直接下载：http://www.angusj.com/resourcehacker/resource_hacker.zip
   - 解压即用，无需安装

2. **打开 CloudMountSetup.exe**
   ```
   File → Open → 选择 dist\CloudMountSetup.exe
   ```

3. **替换图标**
   - 在左侧树形结构中找到：**Icon Group → 1 → 1033**
   - 右键 → **Replace Icon**
   - 选择 `source\icon.ico`（或 `Downloads\favicon.ico`）
   - 点击 **Replace**

4. **保存文件**
   ```
   File → Save （不要用 Save As，直接覆盖原文件）
   ```

5. **验证**
   - 复制到桌面查看图标
   - 右键 → 属性 → 更改图标，确认已嵌入

---

## 替代方案（如果 Resource Hacker 不可用）

### 方案 A：使用 ResHacker 命令行
```batch
ResourceHacker.exe -open dist\CloudMountSetup.exe -save dist\CloudMountSetup.exe -action addoverwrite -res source\icon.ico -mask ICONGROUP,1,
```

### 方案 B：使用 rcedit (Electron 工具)
```bash
npm install -g rcedit
rcedit dist\CloudMountSetup.exe --set-icon source\icon.ico
```

### 方案 C：使用 PE 编辑工具
- PE Explorer
- CFF Explorer
- Stud_PE

---

## 长期改进建议

1. **换用 Inno Setup**：比 NSIS 对图标的支持更好
2. **升级 NSIS**：尝试 NSIS 3.10 或更新版本
3. **使用 NSIS 插件**：如 IconUtils 插件动态设置图标

---

**当前状态**：
- ✅ 安装包功能完整（驱动安装、路径修复等全部完成）
- ⚠️ 图标需要事后手动替换（NSIS 编译时无法加载）

**交付物**：
- `dist\CloudMountSetup.exe` (56 MB, 21:28 最新版本)
- `source\icon.ico` (32 KB, 8-bit BMP 格式)
- Resource Hacker 操作指南（上述步骤）

---

**时间成本对比**：
- 继续调试 NSIS 图标问题：不确定（可能 1-2 小时）
- Resource Hacker 手动替换：5 分钟
- 重构为 Inno Setup：1-2 小时

**建议**：使用 Resource Hacker 手动替换是当前最高效的方案。
