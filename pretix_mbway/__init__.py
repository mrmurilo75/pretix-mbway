from django.utils.translation import gettext_lazy

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")

__version__ = "1.0.0"


class PluginApp(PluginConfig):
    name = "pretix_mbway"
    verbose_name = "MB Way"

    class PretixPluginMeta:
        name = gettext_lazy("MB Way")
        author = "Murilo Rosa"
        description = gettext_lazy("Plugin for use of MB Way payment system")
        visible = True
        version = __version__
        category = "PAYMENT"
        compatibility = "pretix>=2.7.0"

    def ready(self):
        from . import signals  # NOQA


default_app_config = "pretix_mbway.PluginApp"
