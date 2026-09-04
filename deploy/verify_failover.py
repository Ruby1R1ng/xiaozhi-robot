"""Validate installed service environment and stdio MCP; no production mutations."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    pid=subprocess.check_output(['systemctl','show','xiaozhi-search','--property=MainPID','--value'],text=True).strip()
    env=dict(item.split('=',1) for item in Path('/proc/'+pid+'/environ').read_bytes().decode().split('\0') if '=' in item)
    print(json.dumps({'model':env.get('SILICONFLOW_MODEL'),'backup_model':env.get('ZHIPU_MODEL'),
        'zhipu_key_configured':bool(env.get('ZHIPU_API_KEY')),'primary_seconds':env.get('PRIMARY_PIPELINE_TIMEOUT_SECONDS'),'backup_seconds':env.get('BACKUP_PIPELINE_TIMEOUT_SECONDS')},ensure_ascii=False),flush=True)
    assert env['SILICONFLOW_MODEL']=='zai-org/GLM-5.2'
    for label,query,source in [('primary','中国科学院大学是什么学校','web'),
                               ('fallback_timeout','中国科学院大学是什么学校','web'),
                               ('private','郭雷院士的反馈能力研究是什么','knowledge')]:
        child=dict(env,TAVILY_CACHE_TTL_SECONDS='0')
        if label=='fallback_timeout': child['PRIMARY_PIPELINE_TIMEOUT_SECONDS']='0.001'
        params=StdioServerParameters(command=sys.executable,args=['/opt/xiaozhi-search/web_search.py'],cwd='/opt/xiaozhi-search',env=child)
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                response=await session.call_tool('query_information',{'query_text':query,'source':source})
                payload=response.structuredContent or {}
                print(json.dumps({'test':label,'mcp_error':response.isError,**{k:payload.get(k) for k in ['success','provider','summary_model','route','data_source','timing_seconds','fallback_used','failed_attempts']}},ensure_ascii=False),flush=True)
                assert not response.isError and payload.get('success'),label
                if label!='private': assert payload['provider']==('zhipu' if label=='fallback_timeout' else 'tavily_siliconflow')

asyncio.run(main())
