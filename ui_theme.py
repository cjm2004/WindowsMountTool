"""全局 UI 主题：Windows Glass 材质、明暗模式与交互状态。

Tkinter 没有 SwiftUI 的 Liquid Glass 原生 API，因此这里采用对应的桌面实现：
- Windows 11 Mica / Light 材质作为窗口背景；
- 统一的半透明感配色、细边框和层级表面；
- 交互控件只在悬停、按下、焦点和禁用时改变状态；
- 无 pywinstyles 时自动回退到稳定的纯色玻璃表面。
"""
import tkinter as tk
from tkinter import ttk
import winreg

try:
    import pywinstyles
    HAS_GLASS = True
except Exception:
    pywinstyles = None
    HAS_GLASS = False

FONT = 'Microsoft YaHei UI'
VALID_MODES = frozenset(('dark', 'light'))

# 颜色 token。每个表面都保持明确的层级，避免依赖系统主题默认色。
COLORS = {
    'dark': {
        'bg': '#111821',
        'bg_alt': '#17212d',
        'surface': '#1c2734',
        'surface2': '#243342',
        'glass': '#202d3b',
        'glass_hover': '#2b3b4d',
        'glass_pressed': '#334960',
        'border': '#415466',
        'border_strong': '#5c7185',
        'shadow': '#0b1016',
        'text': '#f4f7fb',
        'muted': '#aab8c7',
        'subtle': '#7f91a3',
        'accent': '#6ba9ff',
        'accent_hover': '#8bbcff',
        'accent_pressed': '#4e8fe8',
        'accent_fg': '#08111c',
        'success': '#4bd39a',
        'warning': '#f5c15f',
        'danger': '#f47b82',
        'danger_hover': '#ff9297',
        'field': '#111a24',
        'field_hover': '#182534',
        'field_border': '#42586b',
        'disabled': '#6e7c89',
    },
    'light': {
        'bg': '#e8edf3',
        'bg_alt': '#f1f4f8',
        'surface': '#f6f8fb',
        'surface2': '#e9eef4',
        'glass': '#f9fbfd',
        'glass_hover': '#ffffff',
        'glass_pressed': '#e4edf7',
        'border': '#c3cfdb',
        'border_strong': '#9eafc0',
        'shadow': '#b3bfcc',
        'text': '#182330',
        'muted': '#526273',
        'subtle': '#718295',
        'accent': '#1e73d8',
        'accent_hover': '#0d5fbd',
        'accent_pressed': '#09529f',
        'accent_fg': '#ffffff',
        'success': '#16865d',
        'warning': '#a86600',
        'danger': '#c3313b',
        'danger_hover': '#a92530',
        'field': '#ffffff',
        'field_hover': '#f4f8fc',
        'field_border': '#b2c0ce',
        'disabled': '#8a98a6',
    },
}


# Public token contract used by source copies and simple static checks.
REQUIRED_TOKENS = frozenset({
    'bg', 'bg_alt', 'surface', 'surface2', 'glass', 'glass_hover',
    'glass_pressed', 'border', 'border_strong', 'shadow', 'text', 'muted',
    'subtle', 'accent', 'accent_hover', 'accent_pressed', 'accent_fg',
    'success', 'warning', 'danger', 'danger_hover', 'field', 'field_hover',
    'field_border', 'disabled',
})


def get_system_theme():
    """检测系统当前是浅色还是深色模式。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize',
        ) as key:
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            return 'light' if value == 1 else 'dark'
    except OSError:
        return 'dark'


class Theme:
    """主题管理器：持有当前模式、配色与 ttk 样式。"""

    def __init__(self, root, mode=None):
        self.root = root
        requested = mode or get_system_theme()
        self.mode = requested if requested in VALID_MODES else get_system_theme()
        self.style = ttk.Style(root)
        self._configure()

    @property
    def c(self):
        return COLORS[self.mode]

    def _configure(self):
        c = self.c
        self.style.theme_use('clam')

        # 基础容器与玻璃层级。
        self.style.configure('TFrame', background=c['bg'])
        self.style.configure('Surface.TFrame', background=c['surface'])
        self.style.configure('Surface2.TFrame', background=c['surface2'])
        self.style.configure('Glass.TFrame', background=c['glass'])
        self.style.configure('GlassHover.TFrame', background=c['glass_hover'])
        self.style.configure('Toolbar.TFrame', background=c['bg_alt'])

        # 文本层级。
        self.style.configure('TLabel', background=c['bg'], foreground=c['text'])
        self.style.configure('Surface.TLabel', background=c['surface'], foreground=c['text'])
        self.style.configure('Muted.TLabel', background=c['bg'], foreground=c['muted'])
        self.style.configure('SurfaceMuted.TLabel', background=c['surface'], foreground=c['muted'])
        self.style.configure('Subtle.TLabel', background=c['surface'], foreground=c['subtle'])
        self.style.configure('Title.TLabel', background=c['bg'], foreground=c['text'],
                             font=(FONT, 24, 'bold'))
        self.style.configure('Heading.TLabel', background=c['surface'], foreground=c['text'],
                             font=(FONT, 18, 'bold'))
        self.style.configure('CardHeading.TLabel', background=c['surface2'], foreground=c['text'],
                             font=(FONT, 11, 'bold'))

        # 统一按钮状态。交互玻璃只用于可操作控件。
        self.style.configure('TButton', background=c['glass'], foreground=c['text'],
                             bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['shadow'],
                             padding=(16, 9), relief='flat', focuscolor=c['accent'],
                             focusthickness=1, font=(FONT, 10))
        self.style.map('TButton',
                       background=[('active', c['glass_hover']), ('pressed', c['glass_pressed']),
                                   ('focus', c['glass_hover']), ('disabled', c['surface2'])],
                       foreground=[('disabled', c['disabled'])],
                       bordercolor=[('focus', c['accent']), ('disabled', c['border'])])
        self.style.configure('ThemeToggle.TButton', background=c['glass'], foreground=c['text'],
                             bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['shadow'],
                             padding=(12, 7), relief='flat', focuscolor=c['accent'],
                             focusthickness=1, font=(FONT, 9, 'bold'))
        self.style.map('ThemeToggle.TButton',
                       background=[('active', c['glass_hover']), ('pressed', c['glass_pressed']),
                                   ('focus', c['glass_hover']), ('disabled', c['surface2'])],
                       foreground=[('disabled', c['disabled'])],
                       bordercolor=[('focus', c['accent'])])
        self.style.configure('Primary.TButton', background=c['accent'], foreground=c['accent_fg'],
                             bordercolor=c['accent'], lightcolor=c['accent'], darkcolor=c['accent_pressed'],
                             padding=(18, 10), font=(FONT, 10, 'bold'), relief='flat',
                             focuscolor=c['accent_hover'], focusthickness=1)
        self.style.map('Primary.TButton',
                       background=[('active', c['accent_hover']), ('pressed', c['accent_pressed']),
                                   ('focus', c['accent_hover']), ('disabled', c['border'])],
                       foreground=[('disabled', c['disabled'])],
                       bordercolor=[('focus', c['accent_hover'])])
        self.style.configure('Danger.TButton', background=c['danger'], foreground='#ffffff',
                             bordercolor=c['danger'], lightcolor=c['danger'], darkcolor=c['danger'],
                             padding=(14, 9), relief='flat', focuscolor=c['danger_hover'],
                             focusthickness=1)
        self.style.map('Danger.TButton',
                       background=[('active', c['danger_hover']), ('pressed', c['danger']),
                                   ('focus', c['danger_hover']), ('disabled', c['border'])],
                       foreground=[('disabled', c['disabled'])],
                       bordercolor=[('focus', c['danger_hover'])])

        # 输入控件：统一字段底色、插入符、焦点边框和只读状态。
        self.style.configure('TEntry', fieldbackground=c['field'], foreground=c['text'],
                             insertcolor=c['text'], bordercolor=c['field_border'],
                             lightcolor=c['field_border'], darkcolor=c['field_border'],
                             padding=8, relief='flat', focuscolor=c['accent'])
        self.style.map('TEntry',
                       fieldbackground=[('focus', c['field_hover']), ('disabled', c['surface2'])],
                       foreground=[('disabled', c['disabled'])],
                       bordercolor=[('focus', c['accent']), ('disabled', c['border'])])
        self.style.configure('TCombobox', fieldbackground=c['field'], foreground=c['text'],
                             arrowcolor=c['text'], bordercolor=c['field_border'],
                             lightcolor=c['field_border'], darkcolor=c['field_border'],
                             padding=7, relief='flat', focuscolor=c['accent'])
        self.style.map('TCombobox',
                       fieldbackground=[('readonly', c['field']), ('focus', c['field_hover']),
                                        ('disabled', c['surface2'])],
                       foreground=[('readonly', c['text']), ('disabled', c['disabled'])],
                       bordercolor=[('focus', c['accent']), ('disabled', c['border'])])

        self.style.configure('Horizontal.TProgressbar', background=c['accent'],
                             troughcolor=c['surface2'], borderwidth=0, lightcolor=c['accent'],
                             darkcolor=c['accent'])

        # 保留 ttk 复选框作为回退；主要页面使用 GlassCheckbutton 获得一致的绘制效果。
        self.style.configure('TCheckbutton', background=c['surface'], foreground=c['text'],
                             focuscolor=c['accent'], indicatorcolor=c['surface2'])
        self.style.map('TCheckbutton',
                       background=[('active', c['glass_hover']), ('pressed', c['glass_pressed'])],
                       foreground=[('disabled', c['disabled'])],
                       indicatorcolor=[('selected', c['accent']), ('alternate', c['surface2']),
                                       ('pressed', c['border']), ('disabled', c['surface2'])])

    def apply_glass(self, window=None):
        """应用统一窗口材质；失败时保持 token 颜色回退。"""
        if not HAS_GLASS:
            return
        try:
            target = window or self.root
            pywinstyles.apply_style(target, 'mica' if self.mode == 'dark' else 'light')
        except Exception:
            # 材质是增强效果，不能阻断安装、配置和挂载功能。
            pass

    def glass_colors(self, elevated=False):
        """返回一组统一的玻璃表面颜色，供 tk 原生控件使用。"""
        c = self.c
        surface = c['surface2'] if elevated else c['glass']
        return surface, c['glass_hover'], c['border']

    def set_mode(self, mode):
        if mode not in VALID_MODES:
            raise ValueError(f'不支持的主题模式: {mode!r}')
        self.mode = mode
        self._configure()
        self.apply_glass()
        self.root.configure(bg=self.c['bg'])
        return self.mode

    def toggle(self):
        return self.set_mode('light' if self.mode == 'dark' else 'dark')


class GlassCheckbutton(tk.Frame):
    """使用当前玻璃 token 绘制带焦点、悬停和对号状态的复选框。"""

    def __init__(self, parent, text, variable, theme, command=None):
        super().__init__(parent, bg=theme.c['surface'], highlightthickness=0, bd=0,
                         takefocus=True, cursor='hand2')
        self.theme = theme
        self.variable = variable
        self.command = command
        self._hovered = False
        self._trace = variable.trace_add('write', self._on_variable)
        self.indicator = tk.Canvas(self, width=20, height=20, bg=theme.c['surface'],
                                   highlightthickness=0, bd=0, cursor='hand2')
        self.indicator.pack(side='left', padx=(0, 8))
        self.label = tk.Label(self, text=text, bg=theme.c['surface'], fg=theme.c['text'],
                              font=(FONT, 10), anchor='w', cursor='hand2')
        self.label.pack(side='left', fill='x', expand=True)
        for widget in (self, self.indicator, self.label):
            widget.bind('<Button-1>', self._toggle, add='+')
            widget.bind('<Enter>', self._enter, add='+')
            widget.bind('<Leave>', self._leave, add='+')
        self.bind('<space>', self._toggle, add='+')
        self.bind('<Return>', self._toggle, add='+')
        self.bind('<FocusIn>', self._redraw, add='+')
        self.bind('<FocusOut>', self._redraw, add='+')
        self._draw()

    def _toggle(self, _event=None):
        self.focus_set()
        self.variable.set(not bool(self.variable.get()))
        if self.command:
            self.command()
        return 'break'

    def _enter(self, _event=None):
        self._hovered = True
        self._draw()

    def _leave(self, _event=None):
        self._hovered = False
        self._draw()

    def _redraw(self, _event=None):
        self._draw()

    def _on_variable(self, *_args):
        self._draw()

    def _draw(self):
        c = self.theme.c
        background = c['glass_hover'] if self._hovered else c['surface']
        self.indicator.configure(bg=background)
        self.label.configure(bg=background, fg=c['text'])
        self.configure(bg=background)
        self.indicator.delete('all')
        selected = bool(self.variable.get())
        focused = self.focus_get() == self
        outline = c['accent'] if selected or focused else c['border']
        self.indicator.create_rectangle(
            2, 2, 18, 18, outline=outline,
            fill=c['accent'] if selected else c['surface2'],
            width=2 if focused else 1,
        )
        if selected:
            self.indicator.create_line(5, 10, 9, 14, 15, 6, fill=c['accent_fg'], width=2,
                                       capstyle='round', joinstyle='round')

    def destroy(self):
        try:
            self.variable.trace_remove('write', self._trace)
        except (tk.TclError, AttributeError):
            pass
        super().destroy()


def glass_frame(parent, theme, elevated=True, **kwargs):
    """创建统一的玻璃卡片，集中设置表面、边框和层级。"""
    c = theme.c
    kwargs.setdefault('bg', c['surface2'] if elevated else c['glass'])
    kwargs.setdefault('highlightbackground', c['border'])
    kwargs.setdefault('highlightcolor', c['accent'])
    kwargs.setdefault('highlightthickness', 1)
    kwargs.setdefault('bd', 0)
    return tk.Frame(parent, **kwargs)


def glass_label(parent, theme, text='', muted=False, **kwargs):
    """创建随主题重绘的原生标签。"""
    c = theme.c
    kwargs.setdefault('bg', c['surface2'])
    kwargs.setdefault('fg', c['muted'] if muted else c['text'])
    kwargs.setdefault('font', (FONT, 10))
    return tk.Label(parent, text=text, **kwargs)


def make_theme_toggle(root, theme, on_change=None):
    """在指定父容器创建一个主题切换按钮。"""
    btn = ttk.Button(
        root,
        text='切换到浅色' if theme.mode == 'dark' else '切换到深色',
        style='ThemeToggle.TButton',
        command=lambda: _toggle(btn, theme, on_change),
    )
    return btn


def _toggle(btn, theme, on_change):
    theme.toggle()
    btn.configure(text='切换到浅色' if theme.mode == 'dark' else '切换到深色')
    if on_change:
        on_change(theme.mode)
