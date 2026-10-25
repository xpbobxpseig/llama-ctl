# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['llama_ctl_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('llama_icon.ico', '.'), ('assets/icons/*.png', 'assets/icons'),
           ('THIRD-PARTY-NOTICES.txt', '.')],   # 图标为 Phosphor(MIT) 派生，声明须随分发件同附
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[                                  # C2：只排除构建机带来的第三方臃肿包
        'numpy',            # PIL 懒加载时 import，本工具只读 ICO/PNG，pyd 资源用不到
        'yaml', 'psutil', 'win32', 'pyreadline3', 'charset_normalizer',
        'PIL._avif', 'PIL._webp', 'pydoc_data',
    ],                                          # 注意：email/asyncio/xml/unittest/multiprocessing
                                                # 是 urllib 等 stdlib 的依赖，排除会 ModuleNotFoundError
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='llama_ctl',
    icon='llama_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                  # C2：关 UPX（换冷启动延迟 + AV 误报）
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # C2：onefile 交付——单文件好分发；excludes 已把体积压到 ~11.5 MB
)
