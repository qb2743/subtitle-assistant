from videocaptioner.ui import main


def _create_qt_plugin_root(tmp_path):
    plugin_root = tmp_path / "Lib" / "site-packages" / "PyQt5" / "Qt5" / "plugins"
    (plugin_root / "platforms").mkdir(parents=True)
    media_service = plugin_root / "mediaservice"
    media_service.mkdir()
    (media_service / "wmfengine.dll").touch()
    return plugin_root


def test_windows_prefers_media_foundation(monkeypatch, tmp_path):
    plugin_root = _create_qt_plugin_root(tmp_path)
    monkeypatch.setattr(main.platform, "system", lambda: "Windows")
    monkeypatch.setattr(main.sys, "prefix", str(tmp_path))
    monkeypatch.delenv("QT_MULTIMEDIA_PREFERRED_PLUGINS", raising=False)

    main._configure_qt_plugin_path()

    assert main.os.environ["QT_PLUGIN_PATH"] == str(plugin_root)
    assert main.os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == str(
        plugin_root / "platforms"
    )
    assert (
        main.os.environ["QT_MULTIMEDIA_PREFERRED_PLUGINS"]
        == "windowsmediafoundation"
    )


def test_explicit_multimedia_backend_is_preserved(monkeypatch, tmp_path):
    _create_qt_plugin_root(tmp_path)
    monkeypatch.setattr(main.platform, "system", lambda: "Windows")
    monkeypatch.setattr(main.sys, "prefix", str(tmp_path))
    monkeypatch.setenv("QT_MULTIMEDIA_PREFERRED_PLUGINS", "directshow")

    main._configure_qt_plugin_path()

    assert main.os.environ["QT_MULTIMEDIA_PREFERRED_PLUGINS"] == "directshow"
