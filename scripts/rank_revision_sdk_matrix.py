#!/usr/bin/env python3
"""以冻结模型处理五个补充SDK；参考集只用于最终评价，不参与推断。"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import time
from bspforge.common import read_json, write_json, utc_now, file_sha256

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--only')
    p.add_argument('--experiment-root',type=Path,default=Path('experiments/revision-r1-five-sdk'));a=p.parse_args()
    root=Path.cwd(); output=a.experiment_root.resolve()
    freeze_path=output/'reference-freeze.json'
    freeze=read_json(freeze_path) if freeze_path.exists() else {
        'model_sha256':read_json(root/'reproduction/mdpi-r1/model-contract.json')['deployment_sha256']}
    model=root/'models/structural-prior-feasible-lambdamart-h03-eq-r1-v2.1.txt'
    assert file_sha256(model)==freeze['model_sha256']
    env=dict(os.environ, PYTHONPATH=str(root), OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
             OPENBLAS_NUM_THREADS='4', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for sdk in read_json(output/'manifest.json')['sdks']:
        name=sdk['name']
        if a.only and a.only!=name: continue
        dest=output/name; ir=dest/'ir'/(sdk['sdk_id']+'.json')
        manifest=dest/'ranking-input-manifest.json'
        write_json(manifest,{'schema_version':'1.0','sdks':[sdk]})
        if name=='sifive-fe310':
            old=root/'experiments/revision-r1-20261112/sifive-fe310'
            for f in ['frozen-runtime-bundle.json','semantic-resolution.json','dataset-hardware.json']:
                shutil.copy2(old/f,dest/f)
            continue
        def run(label, script, args, expected):
            if expected.exists(): return
            cmd=[sys.executable,str(root/'scripts'/script),*map(str,args)]
            start=time.monotonic(); print(name,label,'started',flush=True)
            with (dest/(label+'.log')).open('w',encoding='utf-8') as log:
                result=subprocess.run(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
            write_json(dest/(label+'-run.json'),{'command':cmd,'seconds':time.monotonic()-start,'returncode':result.returncode})
            print(name,label,'done',result.returncode,flush=True)
            if result.returncode: raise RuntimeError((name,label))
        base=dest/'dataset-base.json'; field=dest/'dataset-field.json'; hw=dest/'dataset-hardware.json'
        run('01-candidates','build_runtime_operation_dataset.py',['--manifest',manifest,'--ir',ir,'--max-candidates-per-operation',256,'--output',base],base)
        field_model = root/'models/operation-encoder-minilm-l6-v1.0'
        run('02-fields','add_cached_field_late_interaction_scores.py',['--dataset',base,'--output',field,'--model',field_model if field_model.exists() else 'sentence-transformers/all-MiniLM-L6-v2'],field)
        run('03-effects','add_hardware_effect_graph_features.py',['--dataset',field,'--manifest',manifest,'--ir-root',ir.parent,'--output',hw],hw)
        bm=dest/'code-metadata.json'; bv=dest/'code-vectors.npz'; fm=dest/'focused-metadata.json'; fv=dest/'focused-vectors.npz'
        run('04-code','cache_pretrained_code_embeddings.py',['--dataset',hw,'--manifest',manifest,'--ir-root',ir.parent,'--model',root.parent/'models/jina-embeddings-v2-base-code','--output-metadata',bm,'--output-vectors',bv],bv)
        run('05-focused','cache_multiview_effect_embeddings.py',['--dataset',hw,'--manifest',manifest,'--ir-root',ir.parent,'--model',root.parent/'models/jina-embeddings-v2-base-code','--output-metadata',fm,'--output-vectors',fv],fv)
        bundle=dest/'frozen-runtime-bundle.json'
        run('06-export','export_frozen_lambdamart_bundle.py',['--dataset',hw,'--report',root/'experiments/operation-ranking/results-structural-prior-feasible-lambdamart-h03-eq-r1-v2.1.json','--model',model,'--ir',ir,'--sdk-id',sdk['sdk_id'],'--target-architecture','arm' if sdk['architecture'].startswith('arm') else 'riscv','--base-metadata',bm,'--base-vectors',bv,'--focused-metadata',fm,'--focused-vectors',fv,'--max-bundle-candidates',128,'--output',bundle],bundle)
        from bspforge.semantic_resolver import SemanticResolver
        resolution=SemanticResolver().resolve(read_json(ir),method='operation-lambdamart',model_path=bundle,threshold=.42,operation_min_margin=0.)
        write_json(dest/'semantic-resolution.json',resolution)
    write_json(output/'ranking-completion.json',{'created_at':utc_now(),'model_sha256':file_sha256(model),'trained':False})

if __name__=='__main__': main()
