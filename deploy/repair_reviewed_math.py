"""Add verified formula evidence without replacing original chunks or vectors."""
import hashlib,json,sqlite3,sys,time
from pathlib import Path

path=Path(sys.argv[1])
db=sqlite3.connect(path)
row=db.execute("select id,stored_path,sha256 from papers where doi='10.1109/9.895559'").fetchone()
assert row, 'Target DOI missing'
pdf=path.parent/row[1]
assert hashlib.sha256(pdf.read_bytes()).hexdigest()==row[2]=='75910897fdf386f24681f45fa618167a39a63aafd03df66dbfdbe94f0f394edc'
db.execute('''CREATE TABLE IF NOT EXISTS reviewed_math(
 id TEXT PRIMARY KEY,paper_id INTEGER NOT NULL,pdf_page INTEGER,printed_page INTEGER,
 section TEXT,latex TEXT,aliases TEXT,evidence TEXT,answer TEXT,review_status TEXT,provenance TEXT)''')
aliases=['二分之三加根号二','二分之三+根号2','3/2+√2','3/2+sqrt(2)',
         'Xie–Guo constant','Xie Guo constant','谢郭常数','谢–郭常数','谢亮亮郭雷常数',
         'How much uncertainty can be dealt with by feedback','10.1109/9.895559']
evidence=r'''核验依据：原PDF第3页（期刊2205页），Theorem 2.1。以下为带页码的核验转录及中文释义，不是原文逐字中文引文。
系统(1)：y_{t+1}=f(y_t)+u_t+w_{t+1}, t\ge0, y_0\in\mathbb R；未知扰动有界 |w_t|\le w，界w未知。
反馈律(3)：u_t=h_t(y_0,\ldots,y_t)，允许任意因果、非线性、时变反馈。
广义Lipschitz量(4)：\|f\|=\lim_{\alpha\to\infty}\sup_{(x,y)\in\mathbb R^2}\frac{|f(x)-f(y)|}{|x-y|+\alpha}。
不确定集合(7)：\mathcal F(L)=\{f:\|f\|\le L\}。
临界值 L_*=\frac{3}{2}+\sqrt{2}\approx2.914213562。
定理2.1(i)：L<L_*时，存在统一反馈律，使任意f\in\mathcal F(L)和任意初值下，\sup_{t\ge0}(|y_t|+|u_t|)<\infty。
定理2.1(ii)：L\ge L_*时，对任意反馈律及任意初值，都存在集合内某个f使\sup_{t\ge0}|y_t|=\infty。包含等号！不是说每个具体系统均不可控。
这里global stability对应信号有界，不应改述成所有轨迹渐近收敛到零。
Remark 2.1的递推式(8)：a_{n+1}=(L+\frac12)a_n-La_{n-1}, n\ge1。完整证明在后续章节，当前证据卡未核验完整证明。
作者Liang-Liang Xie、Lei Guo；IEEE Transactions on Automatic Control 45(12), 2203–2217, 2000；DOI 10.1109/9.895559。
Xie–Guo constant/谢–郭常数是用户提供的检索别名，本记录不主张它是原论文使用的正式名称。'''
answer='二分之三加根号二约为2.9142，是谢亮亮与郭雷2000年论文中，一类离散时间一阶非线性不确定系统的反馈稳定化临界值。L小于它时，存在统一反馈律使集合内所有系统的输入输出有界；L大于或等于它时，任意反馈律都有集合内的反例，不是每个具体系统都不可控。[1]'
with db:
 db.execute('INSERT OR REPLACE INTO reviewed_math VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('xie-guo-2000-theorem-2.1',row[0],3,2205,'Theorem 2.1; equations (1)-(4),(7),(8)',r'\frac{3}{2}+\sqrt{2}',json.dumps(aliases,ensure_ascii=False),evidence,answer,'visually_verified',json.dumps({'pdf_sha256':row[2],'tool':'PaddleOCR-VL-1.5 + visual inspection','note':'Raw whole-page OCR had errors; only reviewed evidence adopted','reviewed_at':time.strftime('%Y-%m-%d')},ensure_ascii=False)))
print(json.dumps({'reviewed_records':db.execute('select count(*) from reviewed_math').fetchone()[0],
                  'papers':db.execute('select count(*) from papers').fetchone()[0],
                  'original_chunks':db.execute('select count(*) from chunks').fetchone()[0]},ensure_ascii=False))
db.close()
