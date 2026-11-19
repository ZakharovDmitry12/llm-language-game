#!/usr/bin/env python3
"""Analyze an export from lg_game. No network calls and no API keys are needed."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, norm

LANGUAGES = ("English", "Russian")
CELLS = (("English", 0), ("Russian", 0), ("English", 1), ("Russian", 1))
SIGNS = np.array([1., -1., -1., 1.])
PAYOFF_WEIGHTS = np.array([-.5, -.5, .5, .5])
XSET = tuple(range(10, 100, 10))


def _clean(values):
    return np.array([float(v) for v in values if v is not None and not pd.isna(v)], dtype=float)


def contrast_stats(values_by_cell, weights=SIGNS):
    """HC3/Wald saturated-cell contrast; keys are (language, reveal), values may include None.

    Estimates and intervals are missing when the data cannot support them. A zero estimated
    variance is not evidence of infinite precision and therefore has no Wald interval or p-value.
    """
    arrays = [_clean(values_by_cell.get(cell, [])) for cell in CELLS]
    ns = [len(a) for a in arrays]
    out = dict(estimate=np.nan, se_hc3=np.nan, ci_lower=np.nan, ci_upper=np.nan,
               p_value=np.nan, n_min=min(ns), warning="")
    if min(ns) == 0:
        out['warning'] = 'At least one cell has no valid observations.'
        return out
    out['estimate'] = float(np.dot(weights, [a.mean() for a in arrays]))
    if min(ns) < 2:
        out['warning'] = 'At least one cell has fewer than two valid observations.'
        return out
    # Saturated OLS HC3: sum_i (residual_i / (1-1/n))^2 / n^2 = s^2/(n-1).
    var = sum(float(w*w * np.var(a, ddof=1)/(len(a)-1)) for w, a in zip(weights, arrays))
    if var <= 0:
        out['warning'] = 'Zero estimated variance; Wald inference unavailable.'
        return out
    se = np.sqrt(var)
    est = out['estimate']
    out.update(se_hc3=se, ci_lower=est - norm.ppf(.975)*se,
               ci_upper=est + norm.ppf(.975)*se, p_value=2*norm.sf(abs(est/se)))
    return out


def contrast_bounds(values_by_cell, low, high, weights=SIGNS):
    """Worst-case bounds for a contrast, independently replacing each missing outcome."""
    lower, upper = 0., 0.
    for cell, w in zip(CELLS, weights):
        vals = values_by_cell.get(cell, [])
        if len(vals) == 0:
            return (np.nan, np.nan)
        valid = _clean(vals)
        if len(valid) and ((valid < low).any() or (valid > high).any()):
            raise ValueError(f'Outcome outside permitted bounds: {cell}')
        missing = len(vals) - len(valid)
        lb = (valid.sum() + missing*low)/len(vals)
        ub = (valid.sum() + missing*high)/len(vals)
        lower += w * (lb if w >= 0 else ub)
        upper += w * (ub if w >= 0 else lb)
    return float(lower), float(upper)


def holm(values):
    """Holm adjusted p-values. A missing test cannot be claimed as significant."""
    p = np.asarray(values, dtype=float)
    out = np.full(len(p), np.nan)
    indices = np.flatnonzero(np.isfinite(p))
    order = indices[np.argsort(p[indices])]
    # Count all prespecified tests, including unavailable ones, for conservativeness.
    running = 0.
    for rank, idx in enumerate(order):
        running = max(running, (len(p)-rank)*p[idx])
        out[idx] = min(1., running)
    return out


def _write(rows, path, columns=None):
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def _value_counts(df, col, valid_values):
    return pd.to_numeric(df[col], errors='coerce').isin(valid_values)


def _values_for_cells(df, col):
    return {cell: df[(df.language == cell[0]) & (df.reveal == cell[1])][col].tolist()
            for cell in CELLS}


def _stage1(df, output):
    results, curves = [], {}
    for model, data in df.groupby('model', sort=True):
        model_rows = []
        for x in XSET:
            tables, counts = [], []
            for lang in LANGUAGES:
                sub = data[(data.language == lang) & (data.x == x)]
                valid = sub[sub.valid_a]
                a = valid.a.to_numpy(dtype=float)
                yes, no = int((a == 1).sum()), int((a == 0).sum())
                tables.append([yes, no]); counts.append((len(sub), len(a), yes))
                curves[(model,lang,x)] = yes/len(a) if len(a) else np.nan
            p = fisher_exact(tables).pvalue if all(sum(row)>0 for row in tables) else np.nan
            item = dict(model=model, x=x, p_fisher=p)
            for lang, (assigned,n,yes) in zip(LANGUAGES, counts):
                item.update({f'{lang}_assigned': assigned, f'{lang}_valid': n,
                             f'{lang}_accepted': yes,
                             f'{lang}_acceptance': yes/n if n else np.nan})
            model_rows.append(item)
        for row, adj in zip(model_rows, holm([r['p_fisher'] for r in model_rows])):
            row['p_holm_within_model'] = adj
        results.extend(model_rows)
        fig, ax = plt.subplots()
        for lang in LANGUAGES:
            rates = [curves[(model,lang,x)] for x in XSET]
            ax.plot(XSET, rates, marker='o', label=lang)
        ax.set(xlabel='Offer (points)', ylabel='Acceptance rate', ylim=(-.03, 1.03), title=f'{model}: stage I')
        ax.legend(); fig.tight_layout()
        fig.savefig(output / f"acceptance_{safe_name(model)}.png", dpi=140); plt.close(fig)
    _write(results, output/'stage_I_acceptance.csv', ['model','x','English_assigned','English_valid','English_accepted','English_acceptance','Russian_assigned','Russian_valid','Russian_accepted','Russian_acceptance','p_fisher','p_holm_within_model'])
    return results, curves


def safe_name(text):
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(text))


def _stage2(df, output):
    cells, estimates = [], []
    for model, data in df.groupby('model', sort=True):
        for lang, reveal in CELLS:
            sub = data[(data.language == lang) & (data.reveal == reveal)]
            ys, pis = _clean(sub.Y.tolist()), _clean(sub.payoff_p_calculated.tolist())
            cells.append(dict(model=model, language=lang, reveal=reveal, assigned=len(sub),
                              valid_offers=len(ys), mean_offer_fraction=np.mean(ys) if len(ys) else np.nan,
                              valid_payoffs=len(pis), mean_payoff=np.mean(pis) if len(pis) else np.nan))
        y = _values_for_cells(data, 'Y')
        pi = _values_for_cells(data, 'payoff_p_calculated')
        for name, values, weights, low, high in [('offer',y,SIGNS,.1,.9),('payoff',pi,PAYOFF_WEIGHTS,0,90)]:
            s=contrast_stats(values, weights)
            lb,ub=contrast_bounds(values,low,high,weights)
            estimates.append(dict(model=model, outcome=name, **s, missing_bound_lower=lb, missing_bound_upper=ub))
    # Holm family: all models in the input; the intended full experiment includes three.
    rows = [r for r in estimates if r['outcome']=='offer']
    p_family = [r['p_value'] for r in rows] + [np.nan] * max(0, 3-len(rows))
    for row, adj in zip(rows, holm(p_family)):
        row['p_holm_across_models'] = adj
    _write(cells,output/'stage_II_cells.csv')
    _write(estimates,output/'stage_II_contrasts.csv')
    return cells, estimates


def _stage3(df, curves, output):
    rows=[]
    for (model, lang), subset in df.groupby(['model','language'], sort=True):
        vectors=[]
        for raw in subset.loc[subset.status_proposer == 'valid', 'predictions']:
            try:
                v=json.loads(raw) if isinstance(raw,str) else raw
                if not isinstance(v,list) or len(v)!=9: continue
                v=np.asarray(v,dtype=float)
                if not np.isfinite(v).all() or (v<0).any() or (v>1).any(): continue
                vectors.append(v)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        mean=np.mean(vectors,axis=0) if vectors else np.full(9,np.nan)
        for j,x in enumerate(XSET):
            rows.append(dict(model=model,language=lang,x=x,assigned=len(subset),valid_vectors=len(vectors),mean_prediction=mean[j],observed_acceptance=curves.get((model,lang,x),np.nan)))
    _write(rows, output/'stage_III_predictions.csv', ['model','language','x','assigned','valid_vectors','mean_prediction','observed_acceptance'])


def _stage4(df, output):
    rows=[]
    for (model,D,c), sub in df.groupby(['model','D','c'], dropna=False, sort=True):
        valid=sub[(sub.status_proposer == 'valid') & sub.C.isin(LANGUAGES)]
        n=len(valid); nd=int((valid.C==D).sum())
        rows.append(dict(model=model,D=D,c=c,assigned=len(sub),valid_choices=n,choose_D=nd,share_D=nd/n if n else np.nan))
    _write(rows,output/'stage_IV_choice.csv', ['model','D','c','assigned','valid_choices','choose_D','share_D'])



def _derived_outputs(one, two, three, curves, output):
    """Descriptive VOI and separate-sample forecast/offer comparisons."""
    values, voi_rows, predictions, offer_rows = [], [], [], []
    models = sorted(set(one.model.dropna()) | set(two.model.dropna()) | set(three.model.dropna()))
    for model in models:
        p = {(lang,x): curves.get((model,lang,x),np.nan) for lang in LANGUAGES for x in XSET}
        complete = all(np.isfinite(v) for v in p.values())
        for lang in LANGUAGES:
            subset = three[(three.model == model) & (three.language == lang) & (three.status_proposer == 'valid')]
            vectors=[]
            for raw in subset.predictions:
                try:
                    v=np.asarray(json.loads(raw), dtype=float)
                    if v.shape == (9,) and np.isfinite(v).all() and (v>=0).all() and (v<=1).all(): vectors.append(v)
                except (TypeError, ValueError, json.JSONDecodeError): pass
            mean = np.mean(vectors, axis=0) if vectors else np.full(9,np.nan)
            forecast_value=(100-np.asarray(XSET))*mean
            best=np.flatnonzero(np.isclose(forecast_value,np.nanmax(forecast_value))) if len(vectors) else []
            predictions.append(dict(model=model,language=lang,valid_vectors=len(vectors),
                                    predicted_optimal_offers=';'.join(str(XSET[j]) for j in best),
                                    forecast_max_expected_payoff=float(np.nanmax(forecast_value)) if len(vectors) else np.nan))
            for x in XSET:
                v=(100-x)*p[(lang,x)]
                values.append(dict(model=model,language=lang,x=x,acceptance=p[(lang,x)],expected_payoff=v))
            for reveal in (0,1):
                group=two[(two.model==model)&(two.language==lang)&(two.reveal==reveal)]
                for x in XSET:
                    n=int(((group.x==x)&group.valid_x).sum()); nvalid=int(group.valid_x.sum())
                    offer_rows.append(dict(model=model,language=lang,reveal=reveal,x=x,assigned=len(group),valid_offers=nvalid,count=n,share=n/nvalid if nvalid else np.nan))
        if complete:
            arr=np.array([[(100-x)*p[(lang,x)] for x in XSET] for lang in LANGUAGES])
            disclosed=float(arr.max(axis=1).mean())
            hidden=float(arr.mean(axis=0).max())
            voi_rows.append(dict(model=model,optimal_revealed=disclosed,optimal_hidden=hidden,voi=disclosed-hidden,warning='Plug-in estimate uses maxima of noisy rates and may be upward biased.'))
        else:
            voi_rows.append(dict(model=model,optimal_revealed=np.nan,optimal_hidden=np.nan,voi=np.nan,warning='At least one stage I acceptance point is missing; full VOI unavailable.'))
    _write(values,output/'stage_I_expected_values.csv',['model','language','x','acceptance','expected_payoff'])
    _write(voi_rows,output/'stage_I_voi.csv',['model','optimal_revealed','optimal_hidden','voi','warning'])
    _write(predictions,output/'stage_III_optimal_forecasts.csv',['model','language','valid_vectors','predicted_optimal_offers','forecast_max_expected_payoff'])
    _write(offer_rows,output/'stage_II_offer_distribution.csv',['model','language','reveal','x','assigned','valid_offers','count','share'])

def _stage1_stage2_bootstrap(one, two, output, draws, seed):
    rng=np.random.default_rng(seed); rows=[]
    models=sorted(set(one.model.dropna()) | set(two.model.dropna()))
    for model in models:
        a=one[one.model==model]; b=two[two.model==model]
        pools={}
        for lang in LANGUAGES:
            for x in XSET:
                sub=a[(a.language==lang)&(a.x==x)&a.valid_a]
                pools[(lang,x)]=sub.a.to_numpy(float)
        groups={cell:b[(b.language==cell[0])&(b.reveal==cell[1])&b.valid_x].x.to_numpy(float) for cell in CELLS}
        if any(len(v)==0 for v in groups.values()):
            rows.append(dict(model=model,estimate=np.nan,ci_lower=np.nan,ci_upper=np.nan,draws=0,warning='Missing valid offers in a stage II cell.')); continue
        # Needed sums are those offered, avoiding false zero-probability assumptions.
        if any(len(pools[(lang,int(x))])==0 for (lang,_),vals in groups.items() for x in vals):
            rows.append(dict(model=model,estimate=np.nan,ci_lower=np.nan,ci_upper=np.nan,draws=0,warning='An observed offer has no valid stage I acceptance estimates.')); continue
        def calc(ps,gs):
            return float(np.dot(PAYOFF_WEIGHTS, [np.mean([(100-x)*ps[(lang,int(x))] for x in gs[(lang,r)]]) for lang,r in CELLS]))
        original={k: v.mean() for k,v in pools.items() if len(v)}
        est=calc(original,groups); sims=[]
        for _ in range(draws):
            ps={k:rng.choice(v,len(v),replace=True).mean() for k,v in pools.items() if len(v)}
            gs={k:rng.choice(v,len(v),replace=True) for k,v in groups.items()}
            sims.append(calc(ps,gs))
        lo,hi=np.quantile(sims,[.025,.975]) if sims else (np.nan,np.nan)
        rows.append(dict(model=model,estimate=est,ci_lower=lo,ci_upper=hi,draws=draws,warning=''))
    _write(rows,output/'stage_I_II_expected_payoff.csv')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='CSV created by lg_game export')
    parser.add_argument('--output', default='results')
    parser.add_argument('--bootstrap', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=123)
    args=parser.parse_args()
    if args.bootstrap<0: parser.error('--bootstrap must be nonnegative')
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    data=pd.read_csv(args.input, dtype={'task_id':str,'stage':str,'model':str,'language':str,'D':str,'C':str,'predictions':str})
    required={'task_id','stage','model','language','reveal','x','a','payoff_p','payoff_a','D','c','C','predictions','status_proposer','status_responder'}
    if required-set(data.columns): raise SystemExit('Missing columns: '+', '.join(sorted(required-set(data.columns))))
    if data.task_id.duplicated().any(): raise SystemExit('Duplicate task_id found: use the latest deduplicated export.')
    for col in ['reveal','x','a','payoff_p','payoff_a','c']: data[col]=pd.to_numeric(data[col],errors='coerce')
    data['valid_x']=_value_counts(data,'x',XSET) & (data.status_proposer == 'valid')
    # Stage I is an assigned offer, while later offers are generated by the proposer.
    data.loc[data.stage == 'I', 'valid_x'] = _value_counts(data[data.stage == 'I'], 'x', XSET)
    data['valid_a']=_value_counts(data,'a',(0,1)) & (data.status_responder == 'valid')
    # An assigned x is retained even if the responder fails.
    data['Y']=np.where(data.valid_x,data.x/100,np.nan)
    data['payoff_p_calculated']=np.where(data.valid_x & data.valid_a,(100-data.x)*data.a,np.nan)
    one=data[data.stage=='I']; two=data[data.stage=='II']; three=data[data.stage=='III']; four=data[data.stage=='IV']
    _,curves=_stage1(one,out); _stage2(two,out); _stage3(three,curves,out); _stage4(four,out)
    _stage1_stage2_bootstrap(one,two,out,args.bootstrap,args.seed)
    _derived_outputs(one,two,three,curves,out)
    status=data.groupby(['stage','model','status_proposer','status_responder'],dropna=False).size().reset_index(name='n')
    status.to_csv(out/'status_counts.csv',index=False)
    report='''# Analysis notes\n\nGenerated from the assigned-task export, including incomplete tasks. Empty results are not zero.\n\n- Stage II offer is x/100; the primary contrast is (RU,revealed − RU,hidden) − (EN,revealed − EN,hidden). HC3 standard errors and normal 95% intervals are reported only when estimable. Holm uses at least three tests, the prespecified model family; unavailable tests do not produce p-values.\n- Stage II payoff is calculated from valid offers and decisions; the payoff contrast gives both languages weight 1/2. Bounds independently replace missing outcomes with allowed extremes, with signs accounted for.\n- Stage I uses Fisher exact tests with Holm adjustment over nine amounts within each model. This does not adjust across models.\n- The I/II expected payoff comparison bootstraps stage I decisions and stage II offers separately inside their cells, using percentile intervals; it requires at least one valid stage I response for every observed stage II offer.\n- VOI in stage_I_voi.csv compares model-optimal strategies based on the stage I curves; selecting maxima from noisy estimates may bias it upward. It differs from the observed payoff contrast in stage II. A missing stage I curve point makes VOI unavailable.
- Stage III forecasts are separate runs and describe group-level predictions only. The optimal offers based on average forecasts and the stage II offer distribution are in separate CSVs; they are not individual-level comparisons.\n- Stage IV choice rates are descriptive; its statistical test was not specified in the project and should be decided by the researcher before analysis.\n- Repeated requests reflect model/provider/settings, not independent human participants. Results may change with the model version or translation. Examine missingness and drift. Wald and bootstrap intervals rely on assumptions and are unreliable for tiny samples or degenerate variability.\n'''
    (out/'README_analysis.md').write_text(report,encoding='utf-8')
    print(f'Analysis written to {out}')


if __name__=='__main__': main()
