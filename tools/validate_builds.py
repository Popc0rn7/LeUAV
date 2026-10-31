#!/usr/bin/env python3
"""Probe native PC and OHOS builds in the same builder; never run target ELF."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from leuav.resources import load_resources


def main():
    root=Path(__file__).resolve().parents[1]
    entry=load_resources(root).get('ohos_sdk')
    if entry is None:
        raise ValueError('请先绑定资源 ohos_sdk 到 SDK native 根目录')
    sdk=entry['path']
    if not (sdk/'build/cmake/ohos.toolchain.cmake').is_file():
        raise ValueError('OHOS SDK toolchain 缺失')
    output=root/'artifacts/build-probe'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=False)
    report=dict(result='running',sdk_metadata=json.loads((sdk/'oh-uni-package.json').read_text()),targets={})
    try:
        for target,machine in [('pc',62),('ohos',183)]:
            command=['docker','run','--rm','--network','none','--user',f'{os.getuid()}:{os.getgid()}',
                '--env','HOME=/tmp','--mount',f'type=bind,source={root}/environments/probes,target=/probe,readonly',
                '--mount',f'type=bind,source={output},target=/work']
            if target=='ohos':
                command+=['--mount',f'type=bind,source={sdk},target=/sdk,readonly','--env','OHOS_SDK=/sdk','--env','OHOS_ARCH=arm64-v8a']
            build=f'cmake -S /probe -B /work/{target} -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build /work/{target}'
            if target=='pc':build+=' && /work/pc/leuav_build_probe'
            command+=['uav-computer-builder:local',target,'/bin/bash','-c',build]
            with (output/(target+'.log')).open('w') as log:
                subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
            binary=output/target/'leuav_build_probe'
            data=binary.read_bytes()
            assert data[:4]==b'\x7fELF' and data[4:6]==bytes([2,1])
            assert int.from_bytes(data[18:20],'little')==machine
            audit=subprocess.check_output([str(sdk/'llvm/bin/llvm-readelf'),'-h','-l','-d',str(binary)],text=True)
            (output/(target+'-elf.txt')).write_text(audit)
            report['targets'][target]=dict(passed=True,e_machine=machine,executed_on_host=target=='pc')
        report['result']='passed'
    except BaseException as exc:
        report.update(result='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        print(output/'report.json',flush=True)


if __name__=='__main__':main()
