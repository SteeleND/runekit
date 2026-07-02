import io
import logging
import time
from typing import TYPE_CHECKING, Optional

import Quartz
import objc
from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication
import ApplicationServices
from PySide6.QtWidgets import QGraphicsItem

from . import capture
from .capture import NoCapturePermission
from ..instance import GameInstance
from ..psutil_mixins import PsUtilNetStat

if TYPE_CHECKING:
    from .manager import QuartzGameManager

_debug_dump_file = False
logger = logging.getLogger(__name__)

# macOS draws a native title bar above the game's client area. Alt1 expects
# (0, 0) to be the top-left of the client area (like GetClientRect on Windows),
# so we detect and crop the title bar. This is a sane default until the real
# height is measured from the first capture.
DEFAULT_TITLE_BAR_PT = 28


def detect_title_bar_px(gray) -> Optional[int]:
    """Detect the native title bar height (physical px) from a grayscale frame.

    The title bar is a near-uniform dark band at the top; find the first row
    where brightness jumps to the (brighter, varied) game content. Returns None
    if no clear transition is found (e.g. a very dark game scene)."""
    import numpy as np

    h, w = gray.shape
    cx0, cx1 = max(0, w // 2 - 150), min(w, w // 2 + 150)
    limit = min(120, h)
    band = gray[:limit, cx0:cx1].mean(axis=1)
    base = float(band[2]) if limit > 3 else 0.0
    for y in range(4, limit):
        if abs(float(band[y]) - base) > 50:
            return y
    return None


def cgrectref_to_qrect(cgrectref) -> QRect:
    _, cgrect = Quartz.CGRectMakeWithDictionaryRepresentation(cgrectref, None)
    return QRect(
        cgrect.origin.x, cgrect.origin.y, cgrect.size.width, cgrect.size.height
    )


def cgimageref_to_image(imgref) -> Image:
    buf = Quartz.CFDataCreateMutable(None, 0)

    dest = Quartz.CGImageDestinationCreateWithData(buf, "public.tiff", 1, None)
    Quartz.CGImageDestinationAddImage(dest, imgref, None)
    Quartz.CGImageDestinationFinalize(dest)

    buf_size = Quartz.CFDataGetLength(buf)
    py_buf = io.BytesIO()
    py_buf.write(Quartz.CFDataGetBytePtr(buf).as_buffer(buf_size))
    py_buf.seek(0)

    out = Image.open(py_buf, formats=("TIFF",))

    if _debug_dump_file:
        out.save("/tmp/game.bmp")
        open("/tmp/native.xbm", "wb").write(py_buf.getbuffer())

    return out


# This decorator does not support being a class method
@objc.callbackFor(ApplicationServices.AXObserverCreate)
def on_ax_event(observer, element, notification, ptr):
    try:
        self: "QuartzGameInstance" = objc.context.get(ptr)
    except KeyError:
        logger.warning(
            "Received AX event callback for missing pointer %d, removing", ptr
        )
        ApplicationServices.AXObserverRemoveNotification(
            observer, element, notification
        )
        return

    if notification == ApplicationServices.kAXApplicationActivatedNotification:
        self._is_active = True
        self.focusChanged.emit(True)
    elif notification == ApplicationServices.kAXApplicationDeactivatedNotification:
        self._is_active = False
        self.focusChanged.emit(False)
    elif notification == ApplicationServices.kAXWindowResizedNotification:
        self.positionChanged.emit(self.get_position())
    elif notification == ApplicationServices.kAXWindowMovedNotification:
        self.positionChanged.emit(self.get_position())
    else:
        self.logger.warning("Got unknown AX event %s", notification)


class QuartzGameInstance(PsUtilNetStat, GameInstance):
    _is_active = False
    overlay: QGraphicsItem

    __game_last_grab = 0.0
    __game_last_image = None
    _title_bar_pt = DEFAULT_TITLE_BAR_PT
    _title_bar_detected = False

    def __init__(self, manager: "QuartzGameManager", wid, pid, **kwargs):
        super().__init__(**kwargs)
        self.manager = manager
        self.wid = wid
        self.pid = pid
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}:{pid}")
        self.obj_pointer = objc.context.register(self)

        self._setup_observer()
        self.update_is_active()
        self.overlay, self._overlay_disconnect = self.manager.overlay.add_instance(self)

    def _setup_observer(self):
        self._ax_element = ApplicationServices.AXUIElementCreateApplication(self.pid)
        self._ax_observed = [
            ApplicationServices.kAXApplicationActivatedNotification,
            ApplicationServices.kAXApplicationDeactivatedNotification,
            ApplicationServices.kAXWindowResizedNotification,
            ApplicationServices.kAXWindowMovedNotification,
        ]
        err, self._observer = ApplicationServices.AXObserverCreate(
            self.pid, on_ax_event, None
        )
        if err != ApplicationServices.kAXErrorSuccess:
            raise AXAPIError(err)

        for item in self._ax_observed:
            err = ApplicationServices.AXObserverAddNotification(
                self._observer, self._ax_element, item, self.obj_pointer
            )
            if err != ApplicationServices.kAXErrorSuccess:
                raise AXAPIError(err)

        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            ApplicationServices.AXObserverGetRunLoopSource(self._observer),
            Quartz.kCFRunLoopCommonModes,
        )

    def __del__(self):
        self.logger.debug("Destructor")
        for item in self._ax_observed:
            ApplicationServices.AXObserverRemoveNotification(
                self._observer, self._ax_element, item
            )

        objc.context.unregister(self)
        self._overlay_disconnect()

    def get_position(self) -> QRect:
        # The docs say this API is expensive...
        infos = Quartz.CGWindowListCreateDescriptionFromArray([self.wid])
        info = infos[0]  # FIXME: what if window closed
        rect = cgrectref_to_qrect(info[Quartz.kCGWindowBounds])
        # Exclude the native title bar so (0, 0) is the game client area, as
        # Alt1 apps expect. Height of the title bar is refined from the first
        # capture (see grab_game).
        tb = self._title_bar_pt
        return QRect(rect.x(), rect.y() + tb, rect.width(), rect.height() - tb)

    def _device_pixel_ratio(self) -> float:
        """The display's native backing scale (2.0 on Retina). Used only to
        capture at native pixel density before downscaling to logical."""
        screen = QGuiApplication.screenAt(self.get_position().topLeft())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.devicePixelRatio() if screen else 1.0

    def get_scaling(self) -> float:
        # Alt1 image-detection apps (e.g. the clue solver) use fixed pixel
        # offsets calibrated for a standard 1x Windows client and do NOT scale
        # them by rsScaling. So we present the game as a 1x client: grab_game
        # downscales the native Retina capture to logical resolution, and we
        # report rsScaling = 1.0 to match.
        return 1.0

    def is_focused(self) -> bool:
        return self._is_active

    def update_is_active(self):
        self._is_active = (
            Quartz.NSWorkspace.sharedWorkspace()
            .frontmostApplication()
            .processIdentifier()
            == self.pid
        )

    def grab_game(self) -> Image:
        if (time.monotonic() - self.__game_last_grab) * 1000 < self.refresh_rate:
            return self.__game_last_image

        # Capture at native (physical) resolution for maximum sharpness, then
        # downscale to logical with a BOX (area-average) filter. This preserves
        # detail far better than letting ScreenCaptureKit downscale directly,
        # which matters for Alt1 image detection: our tolerant bindFindSubImg
        # matches templates by correlation, and BOX downscaling keeps that
        # correlation high (~0.99) where SCK's downscale drops it (~0.77).
        dpr = self._device_pixel_ratio()
        try:
            imgref = capture.shared_capturer().capture_window(self.wid, dpr)
        except NoCapturePermission:
            self.manager.request_accessibility_popup.emit()
            raise
        if not imgref:
            self.manager.request_accessibility_popup.emit()
            raise NoCapturePermission()

        out = cgimageref_to_image(imgref)

        # Detect and crop the native title bar (physical px) so (0, 0) is the
        # game client area, as Alt1 expects.
        if not self._title_bar_detected:
            import numpy as np

            detected = detect_title_bar_px(np.asarray(out.convert("L")))
            if detected is not None:
                self._title_bar_pt = int(round(detected / dpr))
                self._title_bar_detected = True
                self.positionChanged.emit(self.get_position())

        tb_px = int(round(self._title_bar_pt * dpr))
        if tb_px > 0:
            out = out.crop((0, tb_px, out.width, out.height))

        if dpr != 1.0:
            out = out.resize(
                (int(round(out.width / dpr)), int(round(out.height / dpr))),
                Image.BOX,
            )

        self.__game_last_grab = time.monotonic()
        self.__game_last_image = out
        return out

    def grab_desktop(self, x: int, y: int, w: int, h: int) -> Image:
        imgref = capture.shared_capturer().capture_desktop(x, y, w, h, self.get_scaling())
        if not imgref:
            self.manager.request_accessibility_popup.emit()
            raise NoCapturePermission()

        out = cgimageref_to_image(imgref)
        if out.width != w or out.height != h:
            out = out.resize((w, h), Image.NEAREST)
        return out

    def get_overlay_area(self) -> QGraphicsItem:
        return self.overlay


class AXAPIError(Exception):
    mapping = {
        ApplicationServices.kAXErrorInvalidUIElementObserver: "The observer is not a valid AXObserverRef type",
        ApplicationServices.kAXErrorIllegalArgument: "One or more of the arguments is an illegal value or the length of the notification name is greater than 1024",
        ApplicationServices.kAXErrorNotificationUnsupported: "The observer is not a valid AXObserverRef type",
        ApplicationServices.kAXErrorNotificationAlreadyRegistered: "The notification has already been registered",
        ApplicationServices.kAXErrorCannotComplete: "The function cannot complete because messaging has failed in some way.",
        ApplicationServices.kAXErrorFailure: "There is some sort of system memory failure.",
        ApplicationServices.kAXErrorAPIDisabled: "Assistive applications are not enabled in System Preferences.",
    }

    def __init__(self, code):
        if code == 0:
            raise ValueError("Success")

        super().__init__(self.mapping.get(code, f"API Error: {code}"))
