import os, glob, json, pandas as pd
from sklearn.ensemble import IsolationForest
def _load_many(g):
    frames=[]; 
    for fp in sorted(glob.glob(g)):
        if fp.endswith('.csv'): frames.append(pd.read_csv(fp))
        elif fp.endswith('.json'):
            try: frames.append(pd.read_json(fp))
            except ValueError: frames.append(pd.read_json(fp, lines=True))
    if not frames: raise FileNotFoundError(f'No files matched: {g}')
    return pd.concat(frames, ignore_index=True)
def isolation_forest_detect(input_glob, id_field=None, numeric_fields=None, contamination=0.1, random_state=42, output_path=None):
    df=_load_many(input_glob)
    if numeric_fields is None:
        numeric_fields=[c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    X=df[numeric_fields].fillna(df[numeric_fields].median(numeric_only=True))
    model=IsolationForest(contamination=contamination, random_state=random_state)
    preds=model.fit_predict(X); scores=model.score_samples(X)
    out=df.copy(); out['_iforest_pred']=preds; out['_iforest_score']=scores; out['_is_anomaly']=preds==-1
    anomalies=out[out['_is_anomaly']]
    summary={'rows':len(df),'numeric_fields':numeric_fields,'contamination':contamination,'anomalies':len(anomalies)}
    if id_field and id_field in out.columns: summary['anomalous_ids']=anomalies[id_field].tolist()[:100]
    if output_path: os.makedirs(os.path.dirname(output_path), exist_ok=True); anomalies.to_json(output_path, orient='records', indent=2)
    return {'summary':summary, 'preview': anomalies.head(20).to_dict(orient='records')}
