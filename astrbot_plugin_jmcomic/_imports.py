"""确保 jmcomic 可导入。

优先使用 pip 安装的 jmcomic，否则从配置的 jm_lib_path 加载。
"""
import os
import sys

_jm_imported = False


def ensure_jmcomic_import(config: dict = None) -> None:
    """确保 jmcomic 模块可以被导入"""
    global _jm_imported
    if _jm_imported:
        return

    try:
        import jmcomic  # noqa: F401
        _jm_imported = True
        return
    except ImportError:
        pass

    config = config or {}
    lib_path = config.get("jm_lib_path", "").strip()
    if not lib_path:
        # 尝试从当前文件位置推断项目根目录（开发时）
        lib_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    src_path = os.path.join(lib_path, "src")
    if os.path.isdir(src_path) and src_path not in sys.path:
        sys.path.insert(0, src_path)

    try:
        import jmcomic  # noqa: F401
        _jm_imported = True
    except ImportError:
        raise ImportError(
            "无法导入 jmcomic。请:\n"
            "  1) pip install jmcomic\n"
            "  2) 或在插件配置中设置 jm_lib_path 指向 JMComic-Crawler-Python 项目根目录"
        )
