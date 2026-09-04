"""Run staged installer as root; read new key from stdin, never print it."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path('/opt/xiaozhi-search')
stage = Path('/tmp/xiaozhi-failover-stage')
env = Path('/etc/xiaozhi-search.env')
backup = root / ('backup-failover-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
credentials = json.loads(sys.stdin.readline())
assert credentials.get('zhipu') and '\n' not in credentials['zhipu']
files = ['web_search.py', 'resilient_search.py']
for name in files:
    if (root/name).exists(): shutil.copy2(root/name, backup/name)
shutil.copy2(env, backup/'environment')
os.chmod(backup/'environment',0o600)
unit = Path('/etc/systemd/system/xiaozhi-search.service')
shutil.copy2(unit, backup/'xiaozhi-search.service')
updates = {'SILICONFLOW_MODEL':'zai-org/GLM-5.2', 'ZHIPU_MODEL':'glm-5.1',
           'ZHIPU_API_KEY':credentials['zhipu'], 'PRIMARY_PIPELINE_TIMEOUT_SECONDS':'8',
           'BACKUP_PIPELINE_TIMEOUT_SECONDS':'12'}
lines = [line for line in env.read_text().splitlines() if line.partition('=')[0] not in updates]
lines.extend(k+'='+v for k,v in updates.items())
try:
    for name in files:
        shutil.copy2(stage/name,root/name)
        os.chmod(root/name,0o644)
    # Atomic replacement, restrictive permissions before content is written.
    temp=env.with_suffix('.failover.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f: f.write('\n'.join(lines)+'\n')
    os.replace(temp,env)
    subprocess.run(['systemctl','restart','xiaozhi-search'],check=True)
    subprocess.run(['systemctl','is-active','--quiet','xiaozhi-search'],check=True)
except BaseException:
    for name in files:
        if (backup/name).exists(): shutil.copy2(backup/name,root/name)
    shutil.copy2(backup/'environment',env)
    subprocess.run(['systemctl','restart','xiaozhi-search'])
    raise
print(json.dumps({'backup':str(backup),'installed':files,'service':'active'}))
