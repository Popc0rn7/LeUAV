"""复用官方 AirSim SDK，仅适配固定的旧 RPC 依赖与现有调用契约。"""
from datetime import timedelta
import math
from types import SimpleNamespace

import airsim
import msgpack
import msgpackrpc
from msgpackrpc.error import RPCError, TimeoutError as RPCTimeout
from msgpackrpc.transport import tcp
from tornado.ioloop import IOLoop


# msgpack-rpc-python 0.4.1 使用已被 msgpack 1.x 删除的 encoding 参数。
# 只替换该依赖模块的两个 codec 工厂，不修改全局 msgpack、不实现 RPC 帧/连接。
def _packer(**options):
    options.pop('encoding', None)
    return msgpack.Packer(use_bin_type=True, **options)


def _unpacker(**options):
    options.pop('encoding', None)
    # rpclib 旧图像可能把二进制装进 STR；无损保留非法 UTF-8，随后按字段恢复。
    return msgpack.Unpacker(raw=False, unicode_errors='surrogateescape', **options)


tcp.msgpack = SimpleNamespace(Packer=_packer, Unpacker=_unpacker)


def plain(value, binary=False):
    """官方类型转为既有字典契约；图像保持 bytes，Unicode 名称保持 str。"""
    if binary and isinstance(value, str):
        return value.encode('utf-8', 'surrogateescape')
    if isinstance(value, airsim.MsgpackMixin):
        value = value.to_msgpack()
    if isinstance(value, dict):
        return {key: plain(item, binary=key == 'image_data_uint8') for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


class Session:
    """单线程 SDK 会话；可持续使用，不获取 API 控制权或解锁。"""
    def __init__(self, host='127.0.0.1', port=41451, timeout=10):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout 必须为有限正数')
        self.timeout = timeout
        self.previous_loop = IOLoop.current(instance=False)
        self.client = airsim.MultirotorClient(ip=host, port=port, timeout_value=max(2, math.ceil(timeout)+1))
        self.transport = self.client.client
        self.transport._transport._reconnect_limit = 0
        self.closed = False
        # 官方依赖的周期超时仅精确到秒；追加一次性 deadline，保留雷达的亚秒预算。
        self.transport.call = self._call

    def _call(self, method, *args):
        loop = self.transport._loop
        future = self.transport.send_request(method, args)

        def expired():
            if not future._set_flag:
                future.set_error(RPCTimeout('Request timed out'))
                # 从 pending 表移除，避免持久会话保留已经超时的请求。
                for key, pending in list(self.transport._request_table.items()):
                    if pending is future:
                        self.transport._request_table.pop(key, None)
                loop.stop()

        timer = loop._ioloop.add_timeout(timedelta(seconds=self.timeout), expired)
        try:
            return future.get()
        finally:
            loop._ioloop.remove_timeout(timer)

    def call(self, method, *args):
        if self.closed:
            raise RuntimeError('AirSim SDK 会话已关闭')
        if method.startswith('raw.'):
            # 上游客户端签名与服务端不一致时显式走底层 RPC（如 ADRL 的 simGetObjectPose(name, noisy)）。
            name = method[4:]
            try:
                return plain(self.transport.call(name, *args))
            except RPCTimeout as exc:
                raise TimeoutError(str(exc)) from exc
            except RPCError as exc:
                raise RuntimeError(str(exc)) from exc
        if method == 'simGetImages' and args:
            args = ([airsim.ImageRequest(**item) if isinstance(item, dict) else item for item in args[0]], *args[1:])
        try:
            operation = getattr(self.client, method, None)
            # SDK 已有方法直接调用；场景私有扩展仍委托官方底层 RPC 库。
            value = operation(*args) if callable(operation) else self.transport.call(method, *args)
            return plain(value, binary=method == 'simGetImage')
        except RPCTimeout as exc:
            raise TimeoutError(str(exc)) from exc
        except RPCError as exc:
            raise RuntimeError(str(exc)) from exc

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.transport.close()
        self.transport._loop.dettach_periodic_callback()
        self.transport._loop._ioloop.close(all_fds=True)
        IOLoop.clear_current()
        if self.previous_loop is not None:
            self.previous_loop.make_current()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
