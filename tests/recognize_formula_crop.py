import base64,json,os,time
from pathlib import Path
import httpx
from dotenv import load_dotenv
load_dotenv('/etc/xiaozhi-search.env')
root=Path('/tmp/formula-repair')
for name,prompt in [('constant-formula.png','Formula Recognition:'),('theorem-2-1.png','OCR:')]:
 image=root/name
 r=httpx.post('https://api.siliconflow.cn/v1/chat/completions',headers={'Authorization':'Bearer '+os.environ['SILICONFLOW_API_KEY']},json={
  'model':'PaddlePaddle/PaddleOCR-VL-1.5','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()}},{'type':'text','text':prompt}]}],'max_tokens':2000,'temperature':0},timeout=50)
 r.raise_for_status(); data=r.json()
 image.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'image':name,'result':data['choices'][0]},ensure_ascii=False),flush=True)
