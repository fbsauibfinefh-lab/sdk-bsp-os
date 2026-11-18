"""Recompute paper metrics from the delivered frozen rankings and updated H03."""
import argparse
import json
import math
from pathlib import Path
from statistics import mean

KEYS=['precision_at_1','recall_at_5','hit_at_5','map','ndcg_at_10']
def metrics(ranked,ref,tau=1):
    ranked=list(dict.fromkeys(ranked));positive={s for s,y in ref.items() if y>=tau}
    if not positive:return None
    ranks=[i for i,s in enumerate(ranked,1) if s in positive]
    return dict(zip(KEYS,[float(bool(ranked) and ranked[0] in positive),sum(i<=5 for i in ranks)/len(positive),
                         float(any(i<=5 for i in ranks)),sum(j/i for j,i in enumerate(ranks,1))/len(positive),
                         sum(1/math.log2(i+1) for i in ranks if i<=10)/sum(1/math.log2(i+1) for i in range(1,min(10,len(positive))+1))]))
def avg(rows):return {k:mean(r[k] for r in rows) for k in rows[0]}
def simulation(r):
    ranked=list(dict.fromkeys(tuple(x) for x in r['candidates']))
    allowed={tuple(x) for x in r['reference_pairs']};den=len(set(r['reference_symbols']))
    found=set();hits=[]
    for pair in ranked:
        hit=int(pair in allowed and pair[0] not in found)
        if hit:found.add(pair[0])
        hits.append(hit)
    return dict(zip(KEYS,[float(bool(ranked) and ranked[0] in allowed),sum(hits[:5])/den,float(any(hits[:5])),
                        sum(sum(hits[:i+1])/(i+1) for i,h in enumerate(hits) if h)/den,
                        sum(h/math.log2(i+2) for i,h in enumerate(hits[:10]))/sum(1/math.log2(i+2) for i in range(min(10,den)))]))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--records',type=Path,default=Path(__file__).with_name('H03-evaluation-records-20261117.json'))
    p.add_argument('--output',type=Path,default=Path('H03-verified-metrics.json'))
    args=p.parse_args();j=json.loads(args.records.read_text(encoding='utf-8'))
    assert j['reference_version']=='H03' and j['training_snapshot_unchanged']
    result={'reference_version':'H03','new_training_or_hardware_execution':False,'cohorts':{},'baselines':{},'views':{}}
    for name in ['source','boards']:
        rows=j[name]
        result['cohorts'][name]={str(tau):{'queries':len(ms:=[x for r in rows if (x:=metrics(r['ranked'],r['reference'],tau)) is not None]),'metrics':avg(ms)} for tau in [1,2,3]}
    result['cohorts']['simulation']={'queries':len(j['simulation']),'metrics':avg([simulation(r) for r in j['simulation']])}
    for name in sorted({r['method'] for r in j['baseline_heads']}):
        rs=[r for r in j['baseline_heads'] if r['method']==name]
        result['baselines'][name]=avg([{k:v for k,v in metrics([x['symbol'] for x in r['top5']],r['reference']).items() if k in KEYS[:3]} for r in rs])
    refs={r['group_id']:r['reference'] for r in j['source']}
    for name in sorted({r['condition'] for r in j['view_conditions']}):
        rs=[r for r in j['view_conditions'] if r['condition']==name]
        result['views'][name]=avg([metrics(r['ranked'],refs[r['group_id']]) for r in rs])
    assert abs(result['cohorts']['source']['1']['metrics']['precision_at_1']-258/284)<1e-12
    assert abs(result['cohorts']['boards']['1']['metrics']['precision_at_1']-52/55)<1e-12
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
