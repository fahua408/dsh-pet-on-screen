# -*- coding: utf-8 -*-
r"""build.py — 大肥鱼桌宠钛坦屏投放工具 (BigFishTitanConsole) PyInstaller 打包构建与自动部署脚本。

功能：
1. PyInstaller 构建单目录绿色发布包 (BigFishTitanConsole)
2. 内置 assets, web, ffmpeg.exe 及所有依赖项
3. 自动镜像同步至目标路径：E:\Program Files (x86)\dshpet_screen
4. 自动在桌面生成专属图标快捷方式：大肥鱼桌宠钛坦屏投放工具.lnk
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
APP_DIR = ROOT / 'app'
DIST_DIR = ROOT / 'dist'
BUILD_DIR = ROOT / '_build'

INSTALL_TARGET = Path(r"E:\Program Files (x86)\dshpet_screen")
LG700_SRC = APP_DIR / 'lg700_tool_src'


def clean():
    for d in (DIST_DIR, BUILD_DIR):
        if d.exists():
            shutil.rmtree(d)
    print('✅ 构建临时目录清理完成')


def create_desktop_shortcuts(target_exe: Path, icon_path: Path):
    """创建唯一的 Windows 桌面快捷方式，并清理历史冗余快捷方式。"""
    desktop = Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Desktop'
    for old_name in ('{大肥鱼桌宠钛坦屏投放工具}.lnk', '桌宠之家.lnk', 'DshPetConsole.exe - 快捷方式.lnk'):
        old_p = desktop / old_name
        if old_p.exists():
            try:
                old_p.unlink()
            except Exception:
                pass

    lnk_path = desktop / '大肥鱼桌宠钛坦屏投放工具.lnk'
    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut("{lnk_path}")
    $Shortcut.TargetPath = "{target_exe}"
    $Shortcut.WorkingDirectory = "{target_exe.parent}"
    $Shortcut.IconLocation = "{icon_path}, 0"
    $Shortcut.Description = "大肥鱼桌宠钛坦屏投放工具 · 双桌宠同台水冷屏总控"
    $Shortcut.Save()
    """

    res = subprocess.run(['powershell', '-NoProfile', '-Command', ps_script], capture_output=True, text=True)
    if res.returncode == 0:
        print(f'✅ 已在桌面更新快捷方式：{lnk_path.name}')
    else:
        print(f'⚠️ 创建快捷方式警告：{res.stderr}')


def build():
    icon = APP_DIR / 'assets' / 'app_icon.ico'
    icon_arg = f'--icon={icon}' if icon.exists() else ''

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onedir',
        '--windowed',
        '--name', 'BigFishTitanConsole',
        '--distpath', str(DIST_DIR),
        '--workpath', str(BUILD_DIR),
        '--paths', str(APP_DIR),
        '--paths', str(ROOT),
        '--hidden-import', 'core',
        '--hidden-import', 'core.autostart',
        '--hidden-import', 'core.device',
        '--hidden-import', 'core.pusher',
        '--hidden-import', 'core.dsh_client',
        '--hidden-import', 'core.dsh_renderer',
        '--hidden-import', 'core.dsh_server',
        '--hidden-import', 'core.win32_guard',
        '--hidden-import', 'core.flash_bridge',
        '--hidden-import', 'ui',
        '--hidden-import', 'ui.dashboard',
        '--hidden-import', 'ui.ball',
        '--hidden-import', 'ui.ball_menu',
        '--hidden-import', 'ui.flash_widget',
        '--hidden-import', 'ui.icons',
        '--hidden-import', 'ui.preview',
        '--hidden-import', 'ui.tokens',
        '--hidden-import', 'ui.chat_dialog',
        '--add-data', f'{APP_DIR / "assets"}{os.pathsep}assets',
        '--add-data', f'{APP_DIR / "web"}{os.pathsep}web',
        '--add-data', f'{LG700_SRC}{os.pathsep}lg700_tool_src',
        '--add-binary', f'{APP_DIR / "bin" / "ffmpeg.exe"}{os.pathsep}bin',
        '--collect-data', 'playwright',
    ]

    if icon_arg:
        cmd.append(icon_arg)

    cmd.append(str(APP_DIR / 'main.py'))

    print('🚀 开始打包 BigFishTitanConsole...')
    result = subprocess.run(cmd, check=False)

    if result.returncode == 0:
        dist_app = DIST_DIR / 'BigFishTitanConsole'

        # 补全根目录依赖
        ffmpeg_src = APP_DIR / 'bin' / 'ffmpeg.exe'
        ffmpeg_dst = dist_app / 'ffmpeg.exe'
        if ffmpeg_src.exists():
            shutil.copy2(ffmpeg_src, ffmpeg_dst)

        for folder in ('assets', 'web'):
            src_f = APP_DIR / folder
            dst_f = dist_app / folder
            if src_f.exists():
                if dst_f.exists():
                    shutil.rmtree(dst_f)
                shutil.copytree(src_f, dst_f)

        print(f'✅ 打包构建成功：{dist_app}')

        # 部署安装到目标目录: E:\Program Files (x86)\dshpet_screen
        print(f'📦 正在安装同步至：{INSTALL_TARGET} ...')
        INSTALL_TARGET.mkdir(parents=True, exist_ok=True)
        sync_cmd = ['robocopy', str(dist_app), str(INSTALL_TARGET), '/MIR', '/NFL', '/NDL', '/NJH', '/NJS']
        subprocess.run(sync_cmd, check=False)
        print(f'✅ 安装完成：{INSTALL_TARGET}')

        # 创建桌面快捷方式
        installed_exe = INSTALL_TARGET / 'BigFishTitanConsole.exe'
        installed_ico = INSTALL_TARGET / 'assets' / 'app_icon.ico'
        if not installed_ico.exists():
            installed_ico = icon
        create_desktop_shortcuts(installed_exe, installed_ico)

    else:
        print('❌ 打包失败，请检查上方错误输出')
        sys.exit(1)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--clean', action='store_true', help='仅清理构建产物')
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        build()
