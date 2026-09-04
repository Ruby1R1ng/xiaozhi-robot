"""Reviewed mathematical evidence, stored separately from lossy PDF text."""
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import closing


def normalize_alias(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    value = value.replace('\\frac{3}{2}', '3/2').replace('\\sqrt{2}', 'sqrt2')
    value = value.replace('√2', 'sqrt2').replace('sqrt(2)', 'sqrt2')
    value = value.replace('根号2', '根号二').replace('根号二', 'sqrt2')
    value = value.replace('二分之三', '3/2').replace('加', '+')
    return re.sub(r'[\s‐‑–—\-，。?？!！：:（）()]', '', value)


def lookup(database_path, query):
    start=time.perf_counter()
    norm=normalize_alias(query)
    with closing(sqlite3.connect(f'file:{database_path.as_posix()}?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("select 1 from sqlite_master where name='reviewed_math'").fetchone():
            return None
        for row in db.execute('select m.*,p.title,p.year,p.authors,p.doi,p.official_url,p.stored_path from reviewed_math m join papers p on p.id=m.paper_id where m.review_status=?',('visually_verified',)):
            aliases=json.loads(row['aliases'])
            if not any(normalize_alias(a) in norm for a in aliases): continue
            detail=any(x in norm for x in ['证明','推导','proof','derive','算法','第三','theorem2.2','定理2.2'])
            excerpt=row['evidence']
            result={'title':row['title'],'year':row['year'],'authors':row['authors'],
                    'doi':row['doi'],'official_url':row['official_url'],'stored_path':row['stored_path'],
                    'page_start':row['pdf_page'],'page_end':row['pdf_page'],
                    'printed_page':row['printed_page'],'section':row['section'],
                    'extraction_method':'formula_ocr_plus_visual_review','review_status':row['review_status'],
                    'excerpt':excerpt,'formula_latex':row['latex'],'score':1.0}
            return {'success':True,'query':query,'count':1,'result':[result],
                    'evidence_status':'partial' if detail else 'verified',
                    'relevance_reason':'exact_reviewed_alias',
                    'summary':row['answer'] if not detail else '已定位原论文定理2.1。以下是核验过的条件与结论，不是完整证明；不可据此补造推导。',
                    'warning':'此条已核验；不能据此认为整篇或全库公式均已核验。',
                    'citations':[f"[1] {row['title']} ({row['year']}), PDF p.{row['pdf_page']}, 期刊p.{row['printed_page']}, {row['section']}"],
                    'timing_seconds':{'total':round(time.perf_counter()-start,4)}}
    return None


def relevance(query, records):
    """Conservative lexical support gate, not a calibrated truth probability."""
    mapping={'自适应':'adaptive','反馈':'feedback','系统辨识':'identification','最小二乘':'least squares',
             '随机':'stochastic','稳定':'stability','控制':'control','博弈':'game','多智能体':'multi-agent',
             '参数估计':'parameter','非线性':'nonlinear','饱和':'saturated'}
    text=' '.join(r.get('title','')+' '+r.get('excerpt','') for r in records).casefold()
    q=query.casefold()
    terms=[en for zh,en in mapping.items() if zh in q]
    terms+= [t for t in re.findall(r'[a-z][a-z-]{3,}',q) if t not in {'what','this','that','about','guo','constant','please','explain'}]
    terms=list(dict.fromkeys(terms))
    matched=[t for t in terms if t in text]
    # Matching subject words is evidence of topicality, not a guarantee of answering a theorem.
    exact_title=any(len(r.get('title',''))>15 and normalize_alias(r['title']) in normalize_alias(query) for r in records)
    sufficient=exact_title or (bool(terms) and len(matched)>=min(2,len(terms)))
    if any(x in q for x in ['根号','常数','定理','证明','doi','哪年']): sufficient=False
    return ('candidate' if sufficient else 'insufficient'), matched
