"""Upload an immutable teleop bundle; no process is started or stopped."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import uuid


def shell(target, command):
    marker = '__LEUAV_'+uuid.uuid4().hex+'__'
    wrapped = f"( {command} ); result=$?; printf '\\n{marker}%s\\n' \"$result\""
    result = subprocess.run(['hdc','-t',target,'shell',wrapped],check=True,capture_output=True,text=True,timeout=30)
    match = re.search(r'(?m)^'+re.escape(marker)+r'(\d+)\s*$',result.stdout)
    if not match or int(match[1]) != 0:
        raise RuntimeError('板端命令未确认成功: '+result.stdout+result.stderr)
    return result.stdout[:match.start()]


def validate_bundle(directory):
    directory=directory.resolve(strict=True)
    manifest=json.loads((directory/'manifest.json').read_text())
    release,hashes=manifest['release'],manifest['files']
    if not isinstance(release,str) or not re.fullmatch(r'[0-9a-f]{64}',release) or not isinstance(hashes,dict):
        raise ValueError('运行包清单格式无效')
    if hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()!=release:
        raise ValueError('运行包身份与清单不匹配')
    for name,digest in hashes.items():
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',name) or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
            raise ValueError('运行包文件名无效')
        path=directory/name
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('运行包文件或摘要不匹配: '+name)
    expected=set(hashes)|{'manifest.json','SHA256SUMS'}
    if {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}!=expected:
        raise ValueError('运行包包含清单外文件')
    if (directory/'SHA256SUMS').read_text()!=''.join(f'{digest}  {name}\n' for name,digest in hashes.items()):
        raise ValueError('SHA256SUMS 与清单不匹配')
    return release,expected


def deploy(directory,target):
    directory=Path(directory).resolve()
    if not target or target.startswith('-') or any(c.isspace() for c in target):
        raise ValueError('需要显式有效的 HDC --target')
    release,files=validate_bundle(directory)
    remote='/data/local/workspace/leuav/teleop/releases/'+release
    shell(target,f'test ! -e {remote} && mkdir -p {remote}')
    for name in sorted(files):
        destination=remote+'/'+name
        shell(target,'mkdir -p '+shlex.quote(str(PurePosixPath(destination).parent)))
        subprocess.run(['hdc','-t',target,'file','send',str(directory/name),destination],check=True,timeout=60)
    shell(target,f'cd {remote} && sha256sum -c SHA256SUMS')
    print('上传并校验通过，未启动程序: '+remote)
    print('显式设备 shell 中运行: sh '+remote+'/start.sh')
    return remote


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--target',required=True)
    args=parser.parse_args(argv)
    deploy(args.bundle.expanduser().resolve(),args.target)


if __name__=='__main__':main()
