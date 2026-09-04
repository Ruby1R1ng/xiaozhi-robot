"""Offline page OCR using provider credentials already on the server."""
import asyncio,base64,json,os,time
from pathlib import Path
import httpx
from dotenv import load_dotenv
load_dotenv('/etc/xiaozhi-search.env')

async def main():
 root=Path('/tmp/formula-repair')
 async with httpx.AsyncClient(timeout=90) as client:
  for image in sorted(root.glob('xie-guo-*.png')):
   output=image.with_suffix('.json')
   if output.exists(): continue
   start=time.monotonic()
   r=await client.post('https://api.siliconflow.cn/v1/chat/completions',headers={'Authorization':'Bearer '+os.environ['SILICONFLOW_API_KEY']},json={
    'model':'PaddlePaddle/PaddleOCR-VL-1.5','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()}},{'type':'text','text':'OCR:'}]}], 'max_tokens':7500,'temperature':0,'stream':False})
   r.raise_for_status(); data=r.json()
   output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
   print(json.dumps({'page':image.name,'seconds':round(time.monotonic()-start,2),'finish':data['choices'][0].get('finish_reason'),'text':data['choices'][0]['message']['content']},ensure_ascii=False),flush=True)
asyncio.run(main())
