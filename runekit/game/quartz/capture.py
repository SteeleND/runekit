"""ScreenCaptureKit-based window/desktop capture for macOS.

macOS 15 removed the pixel data returned by the ``CGWindowListCreateImage*``
family (they now return ``NULL``), so the legacy capture path no longer works
on current macOS. Apple's replacement is ScreenCaptureKit (macOS 12.3+, with the
one-shot ``SCScreenshotManager`` API added in macOS 14).

The rest of RuneKit expects a synchronous ``grab`` returning a ``CGImage`` ref,
but ScreenCaptureKit is asynchronous (completion handler delivered on a
background dispatch queue). We bridge the two by blocking the calling thread on
a ``threading.Event`` -- the completion never runs on the calling thread, so
this does not deadlock and needs no CFRunLoop spinning.
"""
import logging
import threading
import time
from typing import Optional

import Quartz
import ScreenCaptureKit as SCK

logger = logging.getLogger(__name__)

# ScreenCaptureKit permission-denied error code.
SC_ERR_TCC_DENIED = -3801

# How long to trust a cached SCShareableContent snapshot before refetching.
_CONTENT_TTL = 1.0
# How long to wait for an async ScreenCaptureKit completion handler.
_CAPTURE_TIMEOUT = 5.0


class NoCapturePermission(Exception):
    def __init__(self):
        super().__init__("Screen Recording permission is not allowed")


class WindowCapturer:
    """Captures on-screen windows/regions via ScreenCaptureKit.

    A single instance is shared across game instances so the (relatively
    expensive) shareable-content enumeration can be cached.
    """

    def __init__(self):
        self._content = None
        self._content_at = 0.0
        self._lock = threading.Lock()

    def _get_content(self, refresh: bool = False):
        with self._lock:
            fresh = (time.monotonic() - self._content_at) < _CONTENT_TTL
            if self._content is not None and fresh and not refresh:
                return self._content

            done = threading.Event()
            box = {}

            def handler(content, err):
                box["content"] = content
                box["err"] = err
                done.set()

            SCK.SCShareableContent.getShareableContentWithCompletionHandler_(handler)
            if not done.wait(_CAPTURE_TIMEOUT):
                logger.warning("Timed out fetching shareable content")
                return self._content

            err = box.get("err")
            if err is not None:
                if err.code() == SC_ERR_TCC_DENIED:
                    raise NoCapturePermission()
                logger.warning("SCShareableContent error: %s", err)
                return self._content

            self._content = box.get("content")
            self._content_at = time.monotonic()
            return self._content

    @staticmethod
    def _find_window(content, wid: int):
        if content is None:
            return None
        for window in content.windows():
            if int(window.windowID()) == int(wid):
                return window
        return None

    def _capture(self, content_filter, config) -> Optional["Quartz.CGImageRef"]:
        done = threading.Event()
        box = {}

        def handler(image, err):
            box["image"] = image
            box["err"] = err
            done.set()

        SCK.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            content_filter, config, handler
        )
        if not done.wait(_CAPTURE_TIMEOUT):
            logger.warning("Timed out capturing image")
            return None

        err = box.get("err")
        if err is not None:
            if err.code() == SC_ERR_TCC_DENIED:
                raise NoCapturePermission()
            logger.warning("SCScreenshotManager error: %s", err)
            return None

        return box.get("image")

    def capture_window(self, wid: int, scale: float = 1.0) -> Optional["Quartz.CGImageRef"]:
        """Capture a single window by CGWindowID at physical resolution.

        SCWindow.frame() is in points; multiplying by the display's backing
        scale (devicePixelRatio) yields the window's native pixel dimensions.
        Alt1 image-detection apps expect the game at physical resolution, so we
        capture at full pixel density rather than downscaling to points.
        """
        content = self._get_content()
        scwindow = self._find_window(content, wid)
        if scwindow is None:
            # Window may be newly created or the cache is stale -- force refresh.
            content = self._get_content(refresh=True)
            scwindow = self._find_window(content, wid)
            if scwindow is None:
                logger.warning("Window %s not found in shareable content", wid)
                return None

        content_filter = (
            SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(scwindow)
        )
        config = SCK.SCStreamConfiguration.alloc().init()
        frame = scwindow.frame()
        config.setWidth_(int(round(frame.size.width * scale)))
        config.setHeight_(int(round(frame.size.height * scale)))
        config.setShowsCursor_(False)
        return self._capture(content_filter, config)

    def capture_desktop(
        self, x: int, y: int, w: int, h: int, scale: float = 1.0
    ) -> Optional["Quartz.CGImageRef"]:
        """Capture a desktop region. Inputs (x, y, w, h) are in physical pixels;
        the returned image is w x h physical pixels."""
        content = self._get_content()
        if content is None or not content.displays():
            return None

        # Region origin/size arrive in physical pixels; SCK source rects are in
        # points, so convert back down by the backing scale.
        px, py = x / scale, y / scale
        pw, ph = w / scale, h / scale

        # Pick the display whose bounds contain the region's origin (in points).
        display = content.displays()[0]
        for candidate in content.displays():
            f = candidate.frame()
            if (
                f.origin.x <= px < f.origin.x + f.size.width
                and f.origin.y <= py < f.origin.y + f.size.height
            ):
                display = candidate
                break

        content_filter = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(
            display, []
        )
        config = SCK.SCStreamConfiguration.alloc().init()
        f = display.frame()
        config.setSourceRect_(
            Quartz.CGRectMake(px - f.origin.x, py - f.origin.y, pw, ph)
        )
        config.setWidth_(int(round(w)))
        config.setHeight_(int(round(h)))
        config.setShowsCursor_(False)
        return self._capture(content_filter, config)


_shared: Optional[WindowCapturer] = None


def shared_capturer() -> WindowCapturer:
    """Return the process-wide capturer, creating it on first use."""
    global _shared
    if _shared is None:
        _shared = WindowCapturer()
    return _shared
