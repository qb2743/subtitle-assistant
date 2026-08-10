"""全局配置快照：批量任务入队时固定当时的设置。

背景：批量任务在轮到每个视频时才通过 TaskFactory 读取全局 cfg 构建任务
配置。若批量运行期间用户在其他面板（如字幕优化与翻译面板）修改了目标
语言、翻译开关等设置，队列中尚未处理的任务会读到新值，导致同一批任务
输出语言不一致。批量任务在入队（点击开始）时创建 ConfigSnapshot，
之后所有视频的任务配置都从快照读取，与运行中的面板设置互不影响。
"""

from qfluentwidgets import ConfigItem

from videocaptioner.ui.common.config import Config, cfg


class _SnapshotItem:
    """与 ConfigItem 保持一致的 .value 取值接口。

    快照对象只需把数据源从全局 cfg 换成快照即可，无需修改
    ``cfg.xxx.value`` 的访问方式。
    """

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class ConfigSnapshot:
    """捕获 Config 全部配置项在某一时刻的取值。

    通过 ``vars(Config)`` 自动枚举所有配置项，新增配置无需手动维护。
    """

    def __init__(self, source=None):
        source = source or cfg
        self._values = {}
        for name, item in vars(Config).items():
            if isinstance(item, ConfigItem):
                self._values[name] = _SnapshotItem(getattr(source, name).value)

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__!r} has no config item {name!r}"
            ) from None
