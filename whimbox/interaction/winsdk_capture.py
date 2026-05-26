"""一种更高效的d3d截图方式，不过需要手动维护缓冲池，暂时不使用"""
import sys

if sys.platform == 'win32':
    from whimbox.interaction.capture import Capture
    from whimbox.common.handle_lib import HANDLE_OBJ
    import asyncio
    from winsdk.windows.ai.machinelearning import LearningModelDevice, LearningModelDeviceKind
    from winsdk.windows.media.capture import MediaCapture
    from winsdk.windows.graphics.capture.interop import create_for_window
    from ctypes.wintypes import HWND
    from winsdk.windows.graphics.capture import (
        Direct3D11CaptureFramePool,
        Direct3D11CaptureFrame,
    )
    from winsdk.windows.graphics.directx import DirectXPixelFormat
    from winsdk.system import Object
    from winsdk.windows.graphics.imaging import (
        SoftwareBitmap,
        BitmapBufferAccessMode,
        BitmapBuffer,
    )
    import threading
    import numpy as np
    from whimbox.common.logger import logger
    import cv2

    def get_direct3d_device():
        try:
          direct_3d_device = LearningModelDevice(LearningModelDeviceKind.DIRECT_X_HIGH_PERFORMANCE).direct3_d11_device
        except: 
          direct_3d_device = None 
        if not direct_3d_device:
            media_capture = MediaCapture()
            async def coroutine():
                await (media_capture.initialize_async() or asyncio.sleep(0))
            asyncio.run(coroutine())
            direct_3d_device = media_capture.media_capture_settings and \
                media_capture.media_capture_settings.direct3_d11_device
        if not direct_3d_device:
            raise OSError("Unable to initialize a Direct3D Device.")
        return direct_3d_device

    class WindowsGraphicsCapture(Capture):
        def __init__(self):
            super().__init__()
            self.max_fps = 30
            self.device = get_direct3d_device()
            self.item = create_for_window(HANDLE_OBJ.get_handle())
            self.frame_pool = None
            self.session = None
            self.last_frame = None
        
        def create_pool(self):
            self.frame_pool = Direct3D11CaptureFramePool.create_free_threaded(
                self.device,
                DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
                1,
                self.item.size,
            )
            self.session = self.frame_pool.create_capture_session(self.item)
            self.session.is_border_required = False
            self.session.is_cursor_capture_enabled = False
            self.session.start_capture()

        async def get_frame(self):
            event_loop = asyncio.get_running_loop()
            self.create_pool()
            fut = event_loop.create_future()

            def frame_arrived_callback(
                frame_pool: Direct3D11CaptureFramePool, event_args: Object
            ):
                frame: Direct3D11CaptureFrame = self.frame_pool.try_get_next_frame()
                fut.set_result(frame)
                self.session.close()
            
            self.frame_pool.add_frame_arrived(
                lambda fp, o: event_loop.call_soon_threadsafe(frame_arrived_callback, fp, o)
            )

            self.session.start_capture()

            frame_fut: Direct3D11CaptureFrame = await fut
            software_bitmap: SoftwareBitmap = await SoftwareBitmap.create_copy_from_surface_async(frame_fut.surface)
            buffer: BitmapBuffer = software_bitmap.lock_buffer(BitmapBufferAccessMode.READ_WRITE)
            image = np.frombuffer(buffer.create_reference(), dtype=np.uint8)
            image.shape = (self.item.size.height, self.item.size.width, 4)
            buffer.close()
            frame_fut.close()
            self._cleanup_session()
            return image
        
        def _cleanup_session(self):
            if self.session:
                try:
                    self.session.close()
                except:
                    pass
                self.session = None
            if self.frame_pool:
                try:
                    self.frame_pool.close()
                except:
                    pass
                self.frame_pool = None
        
        def _get_capture(self):
            return asyncio.run(self.get_frame())

        def _check_shape(self, img:np.ndarray):
            if img.shape == (1080,1920,4):
                return True
            else:
                logger.info("游戏分辨率异常: "+str(img.shape))
                return False
        
        def __del__(self):
            try:
                if self.session:
                    self.session.close()
                if self.frame_pool:
                    self.frame_pool.close()
            except:
                pass