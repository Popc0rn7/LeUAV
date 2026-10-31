#!/usr/bin/env python3
"""PC：为已知 ADRL v1.0 创建独立兼容副本，不修改原始场景包。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import re
import subprocess
import sys
import tempfile

SOURCE_SHA256 = '094ad6b3cb8f55b63a05ab6ca9ee91e18c3eac1d21b64b20451302ba427c68bc'
# clearTrajectory() 中唯一的 moveByVelocityInternal 虚调用。
CALL_VA = 0x2d933a6
EXPECTED = bytes.fromhex('ff90d0020000')
# 保留 rdi/rsi 与栈对齐，调用 vtable[0x50] 的 isApiControlEnabled()。
# false: 返回清理逻辑；true: 恢复零速度参数并尾调用原 vtable[0x2d0]。
GUARD = bytes.fromhex('57564883ec08488b07ff505084c0488d6424085e5f7412488b070f57c00f57c90f57d2ffa0d0020000c3')


LOCKSTEP_VA = 0x2e1b2c2
LOCKSTEP_EXPECTED = bytes.fromhex('0f8509fdffff')
# SITL 已自行启用模拟器；旧包设置/清除 HIL 标志时发送 custom main mode=0。
SITL_HIL_CALLS = {0x2e1b8ab: bytes.fromhex('e820baa204'),
                  0x2e17c9b: bytes.fromhex('e830f6a204')}


def patch(data, *, disable_lockstep=False):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError('场景 ELF 摘要不匹配；拒绝将固定地址补丁用于其他版本')
    data = bytearray(data)
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    segments = []
    for i in range(phnum):
        pos = phoff+i*phsize
        kind, flags, offset, va, _, size, memsize, _ = struct.unpack_from('<IIQQQQQQ', data, pos)
        if kind == 1:
            segments.append((pos, flags, offset, va, size, memsize))
    segment = next(s for s in segments if s[1] & 1 and s[3] <= CALL_VA < s[3]+s[4])
    pos, _, offset, va, size, memsize = segment
    call_offset = offset+CALL_VA-va
    if data[call_offset:call_offset+6] != EXPECTED or size != memsize:
        raise ValueError('补丁位置或 ELF 段布局不匹配')
    # 利用可执行 LOAD 段尾与下一段之间的未使用文件填充；不覆盖原指令/数据。
    guard_va, guard_offset = va+size, offset+size
    next_offset = min(s[2] for s in segments if s[2] > offset)
    if guard_offset+len(GUARD) > next_offset or any(data[guard_offset:guard_offset+len(GUARD)]):
        raise ValueError('ELF 段尾没有预期的零填充空间')
    data[guard_offset:guard_offset+len(GUARD)] = GUARD
    struct.pack_into('<QQ', data, pos+32, size+len(GUARD), memsize+len(GUARD))
    data[call_offset:call_offset+6] = b'\xe8'+struct.pack('<i', guard_va-CALL_VA-5)+b'\x90'
    if disable_lockstep:
        # 此旧包依据 HIL flags/时间戳自动启用锁步，未检查配置的 LockStep。
        # 保留执行器数据更新，跳过自动启用锁步；由 ScalableClock 实时推进。
        site = offset+LOCKSTEP_VA-va
        if data[site:site+6] != LOCKSTEP_EXPECTED:
            raise ValueError('旧包锁步分支指令不匹配')
        data[site:site+6] = b'\xe9'+struct.pack('<i', 0x2e1afd1-LOCKSTEP_VA-5)+b'\x90'
        for address, expected in SITL_HIL_CALLS.items():
            site = offset+address-va
            if data[site:site+5] != expected:
                raise ValueError('旧包 SITL HIL 模式请求指令不匹配')
            # 仅省略两个冗余的 HIL 标志请求；正常模式切换与 Offboard 不改。
            data[site:site+5] = b'\x90'*5
    return bytes(data)


def patch_race_limit(data, symbol_file=None):
    """将原生构造函数内唯一的 300000 ms 校验并写入课程的 300000 ms，拒绝全 ELF 搜索替换。

    调用者先用 SOURCE_SHA256 核对来源。保留符号的 ELF 可直接定位；剥离符号的包
    需要随包 Breakpad .sym 的 FUNC 记录。objdump 只用于反汇编，不执行 ELF。
    """
    with tempfile.NamedTemporaryFile(suffix='.elf') as binary:
        binary.write(data)
        binary.flush()
        spans = []
        for name in ('_ZN12ACompManagerC1Ev', '_ZN12ACompManagerC2Ev'):
            result = subprocess.run(['objdump', '-d', '--insn-width=16', '--disassemble='+name, binary.name],
                                    check=True, capture_output=True, text=True)
            if '<'+name+'>:' in result.stdout:
                spans.append(result.stdout)
        if not spans and symbol_file and Path(symbol_file).exists():
            # Breakpad 地址是相对于最低 LOAD 虚拟地址的 RVA。
            phoff = struct.unpack_from('<Q', data, 32)[0]
            phsize, phnum = struct.unpack_from('<HH', data, 54)
            base = min(struct.unpack_from('<Q', data, phoff+i*phsize+16)[0]
                       for i in range(phnum) if struct.unpack_from('<I', data, phoff+i*phsize)[0] == 1)
            with Path(symbol_file).open(errors='replace') as stream:
                for line in stream:
                    match = re.fullmatch(r'FUNC ([0-9a-fA-F]+) ([0-9a-fA-F]+) \S+ (.*)\n?', line)
                    if match and match[3].strip() in ('ACompManager::ACompManager()', '_ZN12ACompManagerC1Ev', '_ZN12ACompManagerC2Ev'):
                        start = base+int(match[1], 16)
                        result = subprocess.run(['objdump', '-d', '--insn-width=16',
                                                 f'--start-address={start}',
                                                 f'--stop-address={start+int(match[2],16)}', binary.name],
                                                check=True, capture_output=True, text=True)
                        spans.append(result.stdout)
        sites = set()
        for output in spans:
            for line in output.splitlines():
                match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)', line)
                if match and re.search(r'\bmovq?\s+\$0x493e0,0x[0-9a-f]+\(%r[a-z0-9]+\)', match[3]):
                    instruction = bytes.fromhex(match[2])
                    if instruction[:2] == b'\x48\xc7' and instruction.endswith(struct.pack('<I', 300_000)):
                        sites.add((int(match[1], 16), instruction))
        if len(sites) != 1:
            raise ValueError('无法唯一确认原生 5 分钟时限指令；需要匹配的 ADRL.sym/未剥离 ELF，拒绝在线开赛')
        address, instruction = sites.pop()
        phoff = struct.unpack_from('<Q', data, 32)[0]
        phsize, phnum = struct.unpack_from('<HH', data, 54)
        for i in range(phnum):
            kind, flags, offset, va, _, size = struct.unpack_from('<IIQQQQ', data, phoff+i*phsize)
            if kind == 1 and flags & 1 and va <= address < va+size:
                site = offset+address-va
                if data[site:site+len(instruction)] != instruction:
                    break
                result = bytearray(data)
                result[site+len(instruction)-4:site+len(instruction)] = struct.pack('<I', 300_000)
                return bytes(result)
        raise ValueError('原生时限指令不在预期可执行段，拒绝修改')


def patch_end_placement(data, symbol_file=None):
    """只移除 EndRace 中的直接摆位调用；BeginComp 的首次原生摆位保留。

    必须能从 ELF 或随包 Breakpad 符号确认两个函数范围和唯一调用目标。
    外层 prepare 另行校验原始包 SHA256；不猜测未知版本的地址。
    """
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQ', data, phoff+i*phsize)
             for i in range(phnum) if struct.unpack_from('<I', data, phoff+i*phsize)[0] == 1]
    base = min(row[3] for row in loads)
    ranges = {'end': set(), 'place': set()}

    def add(address, size, name):
        key = ('end' if name.startswith('ACompManager::EndRace(') else
               'place' if name.startswith('URace::placeRacersAtStartPositions(') else None)
        if key and size:
            ranges[key].add((address, address+size))

    with tempfile.NamedTemporaryFile(suffix='.elf') as binary:
        binary.write(data)
        binary.flush()
        symbols = subprocess.run(['objdump', '-tC', binary.name], check=True,
                                 capture_output=True, text=True).stdout
        for line in symbols.splitlines():
            match = re.match(r'([0-9a-f]+)\s+.*?\s\.text\s+([0-9a-f]+)\s+(.*)', line)
            if match:
                add(int(match[1], 16), int(match[2], 16), match[3])
        if symbol_file and Path(symbol_file).exists():
            with Path(symbol_file).open(errors='replace') as stream:
                for line in stream:
                    match = re.match(r'FUNC ([0-9a-fA-F]+) ([0-9a-fA-F]+) \S+ (.*)', line)
                    if match:
                        add(base+int(match[1], 16), int(match[2], 16), match[3].strip())
        if any(len(value) != 1 for value in ranges.values()):
            raise ValueError('无法唯一定位 EndRace/原生摆位函数；拒绝启用在线比赛')
        start, stop = next(iter(ranges['end']))
        target, _ = next(iter(ranges['place']))
        output = subprocess.run(['objdump', '-d', '--insn-width=16',
                                 f'--start-address={start}', f'--stop-address={stop}', binary.name],
                                check=True, capture_output=True, text=True).stdout
        sites = []
        for line in output.splitlines():
            match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)', line)
            if match:
                address, instruction = int(match[1], 16), bytes.fromhex(match[2])
                if len(instruction) == 5 and instruction[0] == 0xe8 and address+5+struct.unpack('<i', instruction[1:])[0] == target:
                    sites.append((address, instruction))
        if len(sites) != 1:
            raise ValueError('EndRace 内没有唯一的直接摆位调用；拒绝修改')
        address, instruction = sites[0]
        for _, flags, offset, va, _, size in loads:
            if flags & 1 and va <= address and address+5 <= va+size:
                site = offset+address-va
                if data[site:site+5] == instruction:
                    result = bytearray(data)
                    result[site:site+5] = b'\x90'*5
                    return bytes(result)
        raise ValueError('摆位调用不在可执行段')


def patch_known_online(source, prepared):
    """ADRL v1.0 stripped ELF 的已核实布局；只接受固定原包摘要。

    constructor 2edd5fc 从 7683f0 加载 [race_time=0,max_time=300000]，
    2edd603 写到 this+3e8；Tick 2ede3a2 比较 this+3f0。
    EndRace 2ee1110 收尾后在 2ee1213 调用原生摆位 2ee1b80；
    BeginComp 的 2ee1854 调用保留。
    """
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('在线定点补丁只接受已核实原包摘要')
    checks = {
        0x5683f0: struct.pack('<QQ', 0, 300_000),
        0x2cdd5fc: bytes.fromhex('0f2805edad88fd410f1186e8030000'),
        0x2cde3a2: bytes.fromhex('493b8424f0030000'),
        0x2ce11b5: bytes.fromhex('488bbbd803000066c787640200000000e8c6820000488bbb30020000e81a280000488bbbb0030000e82ec6ffff'),
        0x2ce11e2: bytes.fromhex('66c783b80300000000488dbb2002000031f6e8576efcff'),
        0x2ce11f9: bytes.fromhex('488bbb30020000488db3c003000031d283bb38020000020f95c2e868090000'),
        0x2ce1854: bytes.fromhex('e827030000'),
        0x2ce1b80: bytes.fromhex('415741564154534883ec48837f6802'),
    }
    for offset, expected in checks.items():
        if source[offset:offset+len(expected)] != expected or prepared[offset:offset+len(expected)] != expected:
            raise ValueError(f'在线原包布局不匹配：{offset:#x}')
    result = bytearray(prepared)
    result[0x5683f8:0x568400] = struct.pack('<Q', 300_000)
    result[0x2ce1213:0x2ce1218] = b'\x90'*5
    return bytes(result)


def prepare(source, destination, *, disable_lockstep=False, online_race=False):
    source = source.resolve(strict=True)
    for relative in ('Engine', 'ADRL/Content'):
        if not (source/relative).is_dir():
            raise ValueError(f'场景资源目录缺失：{source/relative}')
    original = source/'ADRL/Binaries/Linux/ADRL'
    source_data = original.read_bytes()
    patched = patch(source_data, disable_lockstep=disable_lockstep)
    if online_race:
        patched = patch_known_online(source_data, patched)
    executable = destination/'ADRL/Binaries/Linux/ADRL'
    executable.parent.mkdir(parents=True, exist_ok=True)
    if executable.exists() and executable.read_bytes() != patched:
        raise RuntimeError(f'拒绝覆盖未知副本：{executable}')
    if not executable.exists():
        executable.write_bytes(patched)
        executable.chmod(0o755)
    for relative in ('Engine', 'ADRL/Content', 'ADRL/Binaries/Linux/ADRL.sym'):
        target = source/relative
        if not target.exists():
            continue
        link = destination/relative
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if link.exists() or link.is_symlink():
            raise RuntimeError(f'拒绝覆盖资源：{link}')
        link.symlink_to(target, target_is_directory=target.is_dir())
    manifest = dict(source=str(source), source_sha256=SOURCE_SHA256,
                    native_race_limit_ms=300_000 if online_race else 300_000,
                    automatic_end_placement=not online_race,
                    patched_sha256=hashlib.sha256(patched).hexdigest(),
                    disable_lockstep=disable_lockstep,
                    lockstep_branch_va=hex(LOCKSTEP_VA) if disable_lockstep else None,
                    skip_sitl_hil_requests=disable_lockstep,
                    guard='clearTrajectory: only send zero velocity when API control is enabled')
    (destination/'compatibility.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return executable
