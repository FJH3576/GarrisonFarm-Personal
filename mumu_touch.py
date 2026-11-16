"""MuMu SDK touch adapter; loaded after the original GarrisonFarm setup."""
import atexit
import ctypes
import json
import os
import time


class MuMuTouch:
    def __init__(self, config, device):
        self.handle = 0
        self.held = False
        self.display = None
        self.last = None
        self.interval = max(0.008, float(config.get('move_interval', 0.016)))
        root = config['emulator_path']
        path = config.get('sdk_path') or os.path.join(root, 'nx_main', 'sdk', 'external_renderer_ipc.dll')
        if not os.path.isfile(path):
            raise RuntimeError('MuMu SDK 不存在: ' + path)
        self.dll = ctypes.CDLL(path)
        signatures = {
            'nemu_connect': [ctypes.c_wchar_p, ctypes.c_int],
            'nemu_disconnect': [ctypes.c_int],
            'nemu_get_display_id': [ctypes.c_int, ctypes.c_char_p, ctypes.c_int],
            'nemu_capture_display': [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.c_void_p],
            'nemu_input_event_finger_touch_down': [ctypes.c_int]*5,
            'nemu_input_event_finger_touch_up': [ctypes.c_int]*3,
        }
        for name, args in signatures.items():
            fn = getattr(self.dll, name)
            fn.argtypes = args
            fn.restype = ctypes.c_int
        index = config.get('instance_index')
        if index is None:
            port = int(str(device).rsplit(':', 1)[1])
            if port < 16384 or (port-16384) % 32:
                raise RuntimeError('无法由 ADB 地址确定 MuMu 实例，请设置 instance_index')
            index = (port-16384)//32
        self.index = int(index)
        try:
            self.handle = self.dll.nemu_connect(root, self.index)
            if not self.handle:
                raise RuntimeError('MuMu SDK 连接失败，实例 ' + str(self.index))
            package = config.get('package_name', 'com.hypergryph.arknights')
            self.display = self.dll.nemu_get_display_id(self.handle, package.encode('utf-8'), 0)
            if self.display < 0:
                raise RuntimeError('未找到明日方舟画面: ' + package)
            w, h = ctypes.c_int(), ctypes.c_int()
            ret = self.dll.nemu_capture_display(self.handle, self.display, 0, ctypes.byref(w), ctypes.byref(h), None)
            if ret or (w.value, h.value) != (1920, 1080):
                raise RuntimeError('MuMu 游戏画面尺寸不匹配: %sx%s (ret=%s)' % (w.value, h.value, ret))
            self.width, self.height = w.value, h.value
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            try:
                if self.held:
                    self.dll.nemu_input_event_finger_touch_up(self.handle, self.display, 1)
            finally:
                self.held = False
                self.dll.nemu_disconnect(self.handle)
                self.handle = 0

    def _point(self, x, y):
        x, y = int(x), int(y)
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError('触控坐标超出画面: %s,%s' % (x, y))
        return x, y

    def _down(self, x, y):
        x, y = self._point(x, y)
        self.held = True  # Release even if the native call reports a partial failure.
        ret = self.dll.nemu_input_event_finger_touch_down(self.handle, self.display, 1, x, y)
        if ret:
            self._abort('MuMu 触控失败: ' + str(ret))
        self.last = (x, y)

    def _up(self):
        if self.held:
            ret = self.dll.nemu_input_event_finger_touch_up(self.handle, self.display, 1)
            if ret:
                self._abort('MuMu 松手失败: ' + str(ret))
            self.held = False

    def _abort(self, message):
        try:
            self.close()
        finally:
            raise RuntimeError(message + '；已停止，避免在拖动中切换触控后端')

    def touch(self, kind, x, y):
        kind = str(kind).upper()
        if kind == 'DOWN':
            if self.held:
                self._up()
            self._down(x, y)
            time.sleep(0.06)
        elif kind == 'MOVE':
            if not self.held:
                raise RuntimeError('MOVE 前没有按下')
            self._down(x, y)
        elif kind == 'UP':
            self._up()
        else:
            raise ValueError('未知触控事件: ' + kind)

    def drag_path(self, x1, y1, x2, y2, steps=12):
        if not self.held:
            raise RuntimeError('拖动前没有按下')
        self._point(x1, y1)
        self._point(x2, y2)
        steps = max(1, int(steps))
        try:
            for i in range(1, steps+1):
                self._down(x1+(x2-x1)*i/steps, y1+(y2-y1)*i/steps)
                time.sleep(self.interval)
        except BaseException:
            self._up()
            raise

    def tap(self, x, y, wait=0.6):
        try:
            self.touch('DOWN', x, y)
        finally:
            self._up()
        time.sleep(wait)

    def swipe(self, x1, y1, x2, y2, ms=500, wait=0.8):
        try:
            self.touch('DOWN', x1, y1)
            steps = max(1, round(float(ms)/1000/self.interval))
            self.drag_path(x1, y1, x2, y2, steps)
        finally:
            self._up()
        time.sleep(wait)


def install(namespace):
    """Only swap all four primitives after successful connection and validation."""
    path = os.path.join(namespace['HERE'], 'mumu_touch.json')
    try:
        with open(path, encoding='utf-8-sig') as f:
            config = json.load(f)
        if not config.get('enabled', True):
            print('[增强触控] 已关闭，使用原 ADB 触控', flush=True)
            return
        controller = MuMuTouch(config, namespace['DEV'])
    except Exception as exc:
        print('[增强触控] 初始化失败，保留原 ADB 触控: ' + str(exc), flush=True)
        return
    atexit.register(controller.close)
    namespace['_mumu_touch_controller'] = controller
    namespace.update({name: getattr(controller, name) for name in ('tap', 'swipe', 'touch', 'drag_path')})
    enable_fast_capture(controller, namespace, config)
    print('[增强触控] MuMu SDK 已启用，实例 %s，display %s；保留原截图和 OCR' % (controller.index, controller.display), flush=True)


def probe(namespace):
    """Read-only SDK connection check; never sends touch events."""
    with open(os.path.join(namespace['HERE'], 'mumu_touch.json'), encoding='utf-8-sig') as f:
        config = json.load(f)
    device = config.get('diagnostic_adb_address', '127.0.0.1:16416')
    controller = MuMuTouch(config, device)
    try:
        print('[增强触控检查] SDK 连接成功，实例 %s，display %s，画面 %sx%s；未发送触控事件' % (controller.index, controller.display, controller.width, controller.height), flush=True)
    finally:
        controller.close()




def enable_fast_capture(controller, namespace, config):
    import threading
    lock = threading.RLock()
    np = namespace['np']
    width, height = controller.width, controller.height
    buffer = (ctypes.c_ubyte * (width*height*4))()

    def capture():
        with lock:
            w, h = ctypes.c_int(width), ctypes.c_int(height)
            ret = controller.dll.nemu_capture_display(controller.handle, controller.display, len(buffer), ctypes.byref(w), ctypes.byref(h), buffer)
            if ret or (w.value,h.value)!=(width,height):
                raise RuntimeError('MuMu SDK 截图失败或尺寸改变: '+str(ret))
            rgba=np.ctypeslib.as_array(buffer).reshape(height,width,4)
            return np.ascontiguousarray(rgba[::-1,:,2::-1])

    if config.get('fast_capture',True):
        namespace['shot']=capture
        print('[快速截图] MuMu SDK 已启用，替代 ADB 截图',flush=True)
