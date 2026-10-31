"""PC：ADRL 原生启动设置与只作用于本次进程窗口的最大化。"""
import ctypes as c
import json
import math
from pathlib import Path
import time

VIEWS = {'Fpv', 'GroundObserver', 'FlyWithMe', 'Manual', 'SpringArmChase', 'Backup', 'NoDisplay'}
LEVELS = {'Building99_Hard', 'Soccer_Field_Easy', 'Soccer_Field_Medium', 'ZhangJiaJie_Medium',
          *(f'{prefix}_Tier_{tier}' for prefix in ('Qualifier', 'Qualification', 'Final') for tier in (1, 2, 3))}


def load_settings(path, *, lockstep=False):
    settings = json.loads(Path(path).read_text())
    level = settings.get('Default Environment', '')
    if level and level not in LEVELS:
        raise ValueError(f'未知 Default Environment：{level}；请使用 ADRL level 名称')
    view = settings.get('ViewMode', '')
    if view and view not in VIEWS:
        raise ValueError(f'未知 ViewMode：{view}；可选 {sorted(VIEWS)}')
    vehicles = settings.get('Vehicles', {})
    if (set(vehicles) != {'PX4', 'drone_2'}
            or vehicles['PX4'].get('VehicleType') != 'PX4Multirotor'
            or vehicles['drone_2'].get('VehicleType') != 'SimpleFlight'):
        raise ValueError('需要 PX4 / PX4Multirotor 和原生赛务占位机 drone_2 / SimpleFlight；原生起跑区摆放要求两个机体')
    expected_clock, expected_lock = ('SteppableClock', True) if lockstep else ('ScalableClock', False)
    if settings.get('ClockType') != expected_clock or vehicles['PX4'].get('LockStep') is not expected_lock:
        raise ValueError(f'场景包要求 ClockType={expected_clock}、PX4.LockStep={str(expected_lock).lower()}'
                         '（实时兼容副本与锁步副本不可混用）')
    return settings


class ClientData(c.Union):
    _fields_ = [('l', c.c_long*5), ('b', c.c_char*20)]


class ClientMessage(c.Structure):
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', ClientData)]


class Event(c.Union):
    _fields_ = [('client', ClientMessage), ('pad', c.c_long*24)]


class Desktop:
    def __init__(self, display):
        self.x = c.CDLL('libX11.so.6')
        signatures = {
            'XOpenDisplay': ([c.c_char_p], c.c_void_p),
            'XDefaultRootWindow': ([c.c_void_p], c.c_ulong),
            'XInternAtom': ([c.c_void_p, c.c_char_p, c.c_int], c.c_ulong),
            'XGetWindowProperty': ([c.c_void_p, c.c_ulong, c.c_ulong, c.c_long, c.c_long,
                                   c.c_int, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int),
                                   c.POINTER(c.c_ulong), c.POINTER(c.c_ulong),
                                   c.POINTER(c.POINTER(c.c_ubyte))], c.c_int),
            'XFree': ([c.c_void_p], c.c_int),
            'XSendEvent': ([c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.POINTER(Event)], c.c_int),
            'XFlush': ([c.c_void_p], c.c_int),
            'XCloseDisplay': ([c.c_void_p], c.c_int),
            'XGetGeometry': ([c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.POINTER(c.c_int),
                              c.POINTER(c.c_int), c.POINTER(c.c_uint), c.POINTER(c.c_uint),
                              c.POINTER(c.c_uint), c.POINTER(c.c_uint)], c.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.x, name)
            function.argtypes, function.restype = args, result
        self.display = self.x.XOpenDisplay(display.encode() if display else None)
        if not self.display:
            raise RuntimeError('无法访问 X11 桌面；检查 DISPLAY 和 Xauthority')
        self.root = self.x.XDefaultRootWindow(self.display)

    def atom(self, name):
        return self.x.XInternAtom(self.display, name.encode(), False)

    def prop(self, window, name):
        actual, count, remaining = c.c_ulong(), c.c_ulong(), c.c_ulong()
        fmt = c.c_int()
        pointer = c.POINTER(c.c_ubyte)()
        rc = self.x.XGetWindowProperty(self.display, window, self.atom(name), 0, 4096, False, 0,
            c.byref(actual), c.byref(fmt), c.byref(count), c.byref(remaining), c.byref(pointer))
        try:
            if rc or fmt.value != 32 or not pointer:
                return []
            values = c.cast(pointer, c.POINTER(c.c_ulong))
            return [int(values[i]) for i in range(count.value)]
        finally:
            if pointer:
                self.x.XFree(pointer)

    def change_state(self, window, action, *names):
        event = Event()
        event.client.type = 33  # ClientMessage
        event.client.display = self.display
        event.client.window = window
        event.client.message_type = self.atom('_NET_WM_STATE')
        event.client.format = 32
        event.client.data.l[0] = action
        for index, name in enumerate(names, 1):
            event.client.data.l[index] = self.atom(name)
        event.client.data.l[3] = 1  # application
        if not self.x.XSendEvent(self.display, self.root, False, (1 << 19) | (1 << 20), c.byref(event)):
            raise RuntimeError('窗口管理器没有接受最大化请求')
        self.x.XFlush(self.display)

    def geometry(self, window):
        root, x, y = c.c_ulong(), c.c_int(), c.c_int()
        width, height, border, depth = (c.c_uint() for _ in range(4))
        if not self.x.XGetGeometry(self.display, window, c.byref(root), c.byref(x), c.byref(y),
            c.byref(width), c.byref(height), c.byref(border), c.byref(depth)):
            raise RuntimeError('无法读取本次场景窗口尺寸')
        return {'width': width.value, 'height': height.value}

    def close(self):
        self.x.XCloseDisplay(self.display)


def maximize_window(pid, display, timeout=10):
    """EWMH 最大化保留窗口边框/桌面面板，只匹配本次进程 PID。"""
    desktop = Desktop(display)
    deadline = time.monotonic()+timeout
    try:
        window = None
        while time.monotonic() < deadline:
            windows = desktop.prop(desktop.root, '_NET_CLIENT_LIST')
            window = next((w for w in windows if desktop.prop(w, '_NET_WM_PID') == [pid]), None)
            if window is not None:
                break
            time.sleep(.1)
        if window is None:
            raise RuntimeError('未找到本次 ADRL 的受管理窗口；最大化需要支持 EWMH 的 X11/XWayland 桌面')
        desktop.change_state(window, 0, '_NET_WM_STATE_FULLSCREEN')
        names = ['_NET_WM_STATE_MAXIMIZED_HORZ', '_NET_WM_STATE_MAXIMIZED_VERT']
        desktop.change_state(window, 1, *names)
        expected = {desktop.atom(name) for name in names}
        fullscreen = desktop.atom('_NET_WM_STATE_FULLSCREEN')
        while time.monotonic() < deadline:
            states = set(desktop.prop(window, '_NET_WM_STATE'))
            if expected <= states and fullscreen not in states:
                time.sleep(.1)  # 等待 WM 的 ConfigureNotify 应用到客户区尺寸。
                return dict(mode='maximized', fullscreen=False, pid=pid, window=hex(window),
                            **desktop.geometry(window))
            time.sleep(.1)
        raise RuntimeError('窗口管理器未确认窗口最大化，拒绝写作已生效')
    finally:
        desktop.close()


def load_level(runtime, state, level, deadline, already_loaded=False):
    if not level:
        return
    print(f'加载默认 level：{level}（不解锁、不启动比赛）…', flush=True)
    if not already_loaded:
        result = runtime.rpc(state, 'simLoadLevel', level)
        if result is not True:
            raise RuntimeError(f'默认 level 加载失败：{level}，返回 {result!r}')
    loaded_at = time.monotonic()
    stable = 0
    while time.monotonic() < deadline:
        if not runtime.process_manager.host_alive(state):
            raise RuntimeError('加载 level 后场景退出；查看 airsim-console.log')
        gates = runtime.rpc(state, 'simListSceneObjects', 'Gate.*')
        settled = all(math.sqrt(sum(v*v for v in runtime.rpc(state, 'getMultirotorState', name)
                                   ['kinematics_estimated']['linear_velocity'].values())) < .1
                      for name in ('PX4', 'drone_2'))
        if gates and settled and runtime.ready(state, require_preflight=False) and time.monotonic()-loaded_at >= 2:
            stable += 1
            if stable >= 3:
                state['level_loaded'] = dict(name=level, gate_count=len(gates), gates=gates)
                runtime.process_manager.write_state(runtime.STATE_DIR, state)
                print(f'{level} 已加载，赛门 {len(gates)} 个；切图后传感器/定位已重新就绪', flush=True)
                return
        else:
            stable = 0
        time.sleep(1)
    raise RuntimeError(f'{level} 加载后赛门/传感器/定位未就绪；查看本轮日志')


def prepare_race(runtime, state, settings, deadline):
    level = settings.get('Default Environment', '')
    if level:
        print('先加载默认地图，再启动 PX4，避免已运行 HIL 跨地图时钟/原点重置。', flush=True)
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError('PX4 启动前场景 RPC 未就绪')
            try:
                if runtime.rpc(state, 'ping'):
                    break
            except (OSError, RuntimeError):
                if time.monotonic() > deadline:
                    raise RuntimeError('PX4 启动前场景 RPC 未就绪')
            time.sleep(.5)
        if runtime.rpc(state, 'simLoadLevel', level) is not True:
            raise RuntimeError(f'默认地图加载失败：{level}')
        time.sleep(2)
        runtime.rpc(state, 'simResetRace')
        time.sleep(1)
        slots = {name: runtime.rpc(state, 'simGetVehiclePose', name) for name in ('PX4', 'drone_2')}
        for pose in slots.values():
            if not all(math.isfinite(v) for values in pose.values() for v in values.values()):
                raise RuntimeError('原生起跑区摆放位姿无效')
        if math.dist(list(slots['PX4']['position'].values()),
                     list(slots['drone_2']['position'].values())) < .01:
            raise RuntimeError('原生赛务未分配两个不同出发位，拒绝回退到 PlayerStart')
        start_pose = slots['PX4']
        state['race'] = dict(phase='prepared', tier=2, start_positions=slots,
                             placement='native start_block / race_start')
    return start_pose if level else None


def verify_race(runtime, state, settings, start_pose, deadline):
    level = settings.get('Default Environment', '')
    load_level(runtime, state, level, deadline, already_loaded=True)
    if level:
        actual_pose = runtime.rpc(state, 'simGetVehiclePose', 'PX4')
        expected, actual = start_pose['position'], actual_pose['position']
        error_xy = math.hypot(expected['x_val']-actual['x_val'], expected['y_val']-actual['y_val'])
        qa, qb = start_pose['orientation'], actual_pose['orientation']
        angle = math.degrees(2*math.acos(min(1., abs(sum(qa[key]*qb[key] for key in qa)))))
        if error_xy > .15 or angle > 5:
            raise RuntimeError('原生固定出发位准备未生效，拒绝标记就绪')
        state['race_reset'] = dict(native_start=start_pose, after=actual_pose,
                                  horizontal_error_m=error_xy, orientation_error_deg=angle,
                                  api_control=runtime.rpc(state, 'isApiControlEnabled', 'PX4'))
