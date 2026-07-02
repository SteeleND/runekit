from PySide6.QtWebEngineCore import (
    QWebEngineUrlScheme,
)


class RuneKitScheme(QWebEngineUrlScheme):
    scheme = b"rk"

    def __init__(self):
        super().__init__(self.scheme)
        self.setSyntax(QWebEngineUrlScheme.Syntax.Path)
        self.setDefaultPort(QWebEngineUrlScheme.SpecialPort.PortUnspecified.value)
        self.setFlags(
            QWebEngineUrlScheme.SecureScheme
            | QWebEngineUrlScheme.ContentSecurityPolicyIgnored
            | QWebEngineUrlScheme.CorsEnabled
        )


class Alt1Scheme(QWebEngineUrlScheme):
    scheme = b"alt1"

    def __init__(self):
        super().__init__(self.scheme)
        self.setSyntax(QWebEngineUrlScheme.Syntax.Path)
        self.setDefaultPort(QWebEngineUrlScheme.SpecialPort.PortUnspecified.value)


def register():
    QWebEngineUrlScheme.registerScheme(Alt1Scheme())
    QWebEngineUrlScheme.registerScheme(RuneKitScheme())
