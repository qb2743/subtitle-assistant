"""GUI entry point — launchable via `videocaptioner` (no args) or `python -m videocaptioner.ui.main`."""

import os
import platform
import sys
from pathlib import Path


def _configure_qt_plugin_path() -> None:
    """Point Qt at the bundled PyQt platform plugins before QApplication starts.

    On Windows, Qt 5 can mangle non-ASCII source paths when deriving
    ``QLibraryInfo`` paths.  This project is commonly checked out under a
    Chinese directory, so set the plugin paths explicitly and prefer only
    candidates that actually exist.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "PyQt5" / "Qt5" / "plugins")
    lib_folder = "Lib" if platform.system() == "Windows" else "lib"
    candidates.append(
        Path(sys.prefix) / lib_folder / "site-packages" / "PyQt5" / "Qt5" / "plugins"
    )

    for plugin_root in candidates:
        platforms = plugin_root / "platforms"
        if not platforms.is_dir():
            continue
        os.environ["QT_PLUGIN_PATH"] = str(plugin_root)
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms)
        return


def main():
    import traceback

    # Must run before QApplication is constructed; importing Qt modules alone
    # does not load a platform plugin yet.
    _configure_qt_plugin_path()

    from PyQt5.QtCore import Qt, QTranslator
    from PyQt5.QtWidgets import QApplication

    from videocaptioner.config import TRANSLATIONS_PATH
    from videocaptioner.core.utils.cache import disable_cache, enable_cache
    from videocaptioner.core.utils.logger import setup_logger

    # Suppress qfluentwidgets ad
    with open(os.devnull, "w") as _devnull:
        sys.stdout, _stdout = _devnull, sys.stdout
        from qfluentwidgets import FluentTranslator
        sys.stdout = _stdout

    from videocaptioner.ui.common.config import cfg

    # sherpa-onnx requires its bundled ORT 1.24; load it before other native modules.
    if sys.platform == "win32":
        import sherpa_onnx  # noqa: F401

    from videocaptioner.ui.view.main_window import MainWindow

    # Logger + global exception hook
    logger = setup_logger("字幕助手")

    def exception_hook(exctype, value, tb):
        logger.error("".join(traceback.format_exception(exctype, value, tb)))
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = exception_hook

    # Cache
    if cfg.get(cfg.cache_enabled):
        enable_cache()
    else:
        disable_cache()

    # DPI scaling
    if cfg.get(cfg.dpiScale) == "Auto":
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough  # type: ignore
        )
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # type: ignore
    else:
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        os.environ["QT_SCALE_FACTOR"] = str(cfg.get(cfg.dpiScale))
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)  # type: ignore

    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)  # type: ignore

    # i18n
    locale = cfg.get(cfg.language).value
    app.installTranslator(FluentTranslator(locale))
    my_translator = QTranslator()
    my_translator.load(str(TRANSLATIONS_PATH / f"VideoCaptioner_{locale.name()}.qm"))
    app.installTranslator(my_translator)

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
