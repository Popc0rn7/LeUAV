#!/usr/bin/env python3
"""Build the three local base images and record their identities; no simulation."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'artifacts/images'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=False)
    targets=[('uav-computer-builder:local','environments/humble/Dockerfile',['--target','builder']),
             ('uav-computer:local','environments/humble/Dockerfile',['--target','computer']),
             ('flight_board:local','environments/flight_board/Dockerfile',[])]
    baseline=json.loads(subprocess.check_output(['docker','image','inspect','uav-computer-ohos:local'],text=True))[0]
    expected='sha256:ce4401623e23a88e84d426778b66bc988d44aa2f653c4362d4f114e8e634ab2c'
    if baseline['Id'] != expected:
        raise RuntimeError('构建依赖基线身份变化，停止；核实版本后再更新配方与记录')
    report=dict(result='running',builder_baseline=expected,images={},sources={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root/'environments').rglob('*')) if p.is_file() and '__pycache__' not in p.parts})
    try:
        for image,recipe,extra in targets:
            print('构建 '+image,flush=True)
            with (output/(image.split(':')[0]+'.log')).open('w') as log:
                subprocess.run(['docker','build','--pull=false','--network','none',*extra,'-t',image,'-f',recipe,'.'],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
            metadata=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
            report['images'][image]=dict(id=metadata['Id'],size=metadata['Size'],labels=metadata.get('Config',{}).get('Labels'))
        report['result']='passed'
    except BaseException as exc:
        report.update(result='failed',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        print(str(output/'report.json'),flush=True)


if __name__=='__main__':main()
