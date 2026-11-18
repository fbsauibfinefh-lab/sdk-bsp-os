#!/usr/bin/env python3
"""记录真人迁移任务的互斥主动/等待阶段，不预填任何工时。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

STAGES=('preparation','initial-build','first-validation','repair','unspecified')


def summarize(events: list[dict]) -> dict:
    totals={'active':0.0,'wait':0.0}
    stages={stage:{'active':0.0,'wait':0.0,'pause':0.0,'elapsed':0.0} for stage in STAGES}
    for first,second in zip(events,events[1:]):
        delta=(datetime.fromisoformat(second['time'])-datetime.fromisoformat(first['time'])).total_seconds()
        if delta<0:
            raise ValueError('事件时间不能逆序')
        stage=first.get('stage','unspecified')
        if stage not in stages:raise ValueError('未知计时阶段')
        stages[stage]['elapsed']+=delta
        if first['mode'] in ('active','wait','pause'):stages[stage][first['mode']]+=delta
        if first['mode'] in totals:
            totals[first['mode']]+=delta
    for value in stages.values():value['net_wall']=value['active']+value['wait']
    milestones={event['milestone']:event['time'] for event in events if event.get('milestone')}
    return {'closed_intervals_seconds':totals,'stage_seconds':stages,
            'primary_first_build_active_seconds':stages['initial-build']['active'],
            'primary_first_build_net_wall_seconds':stages['initial-build']['net_wall'],
            'secondary_engineering_active_seconds':stages['initial-build']['active']+stages['repair']['active'],
            'secondary_acceptance_net_wall_seconds':sum(stages[s]['net_wall'] for s in ['initial-build','first-validation','repair']),
            'milestones':milestones,'open_interval_mode':events[-1]['mode'] if events else None,
            'completed':bool(events) and events[-1]['mode']=='finish',
            'note':'首次构建是主效率终点；首次固定验收另列；修复包括诊断、修改、重构建、烧录及复测。暂停和公共准备不计主指标；未关闭区间不累计。'}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--log',type=Path,required=True)
    p.add_argument('--participant')
    p.add_argument('--task')
    p.add_argument('--condition',choices=['manual','assisted'])
    p.add_argument('--mode',choices=['active','wait','pause','finish'])
    p.add_argument('--phase')
    p.add_argument('--stage',choices=STAGES,default='unspecified')
    p.add_argument('--milestone',choices=['task-start','first-build','first-validation-passed','first-validation-failed','accepted','stopped'])
    p.add_argument('--summarize',action='store_true')
    p.add_argument('--note',default='')
    a=p.parse_args()
    events=[]
    if a.log.exists():
        events=[json.loads(line) for line in a.log.read_text(encoding='utf-8').splitlines() if line]
    if a.summarize:
        print(json.dumps(summarize(events),ensure_ascii=False,indent=2));return 0
    if not all([a.participant,a.task,a.condition,a.mode,a.phase]):p.error('记录事件需要participant、task、condition、mode和phase')
    identity={'participant':a.participant,'task':a.task,'condition':a.condition}
    if events and any(events[0][k]!=v for k,v in identity.items()):
        raise ValueError('一个日志只能记录一次固定参与者/任务/条件')
    if events and events[-1]['mode']=='finish':
        raise ValueError('任务已结束，应使用新日志')
    if a.milestone and any(e.get('milestone')==a.milestone for e in events):raise ValueError('同一里程碑只能记录一次')
    event={**identity,'time':datetime.now(timezone.utc).isoformat(),'mode':a.mode,'phase':a.phase,
           'stage':a.stage,'milestone':a.milestone,'note':a.note}
    result=summarize([*events,event])
    a.log.parent.mkdir(parents=True,exist_ok=True)
    with a.log.open('a',encoding='utf-8') as f:
        f.write(json.dumps(event,ensure_ascii=False)+'\n')
    a.log.with_suffix('.summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
