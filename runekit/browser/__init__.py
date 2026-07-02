from .api import Alt1WebChannel, Alt1Api
from .profile import WebProfile
from .scheme import register as register_scheme


def init():
    # Qt6 removed QtWebEngine.initialize(); the widgets backend initializes
    # lazily. Custom URL schemes must still be registered before the
    # QApplication is constructed.
    register_scheme()
