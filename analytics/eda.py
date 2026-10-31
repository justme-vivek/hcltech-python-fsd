from pathlib import Path
import argparse, json
import pandas as pd
import matplotlib.pyplot as plt

COLUMNS=["timestamp","service_name","endpoint","method","response_time_ms","status_code","user_id"]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",default="data/raw/dataset.csv")
    args=parser.parse_args()
    src=Path(args.input)
    if not src.exists():
        raise SystemExit(f"Dataset not found: {src}. Place the supplied dataset.csv at data/raw/dataset.csv; raw data is never generated or overwritten.")
    out=Path("analytics/outputs"); out.mkdir(parents=True,exist_ok=True)
    df=pd.read_csv(src)
    missing=set(COLUMNS)-set(df.columns)
    if missing: raise SystemExit(f"Missing required columns: {sorted(missing)}")
    df["timestamp"]=pd.to_datetime(df["timestamp"],errors="coerce")
    df["response_time_ms"]=pd.to_numeric(df["response_time_ms"],errors="coerce")
    df["status_code"]=pd.to_numeric(df["status_code"],errors="coerce").astype("Int64")
    cleaned=df.dropna(subset=COLUMNS).drop_duplicates().sort_values("timestamp").copy()
    cleaned.to_csv("data/processed/dataset_cleaned.csv",index=False)
    cleaned["is_error"]=cleaned.status_code>=400
    cleaned["is_4xx"]=cleaned.status_code.between(400,499)
    cleaned["is_5xx"]=cleaned.status_code.between(500,599)
    metrics={"rows_raw":len(df),"rows_cleaned":len(cleaned),"nulls":df.isna().sum().to_dict(),
      "duplicates":int(df.duplicated().sum()),"latency_ms":{"mean":float(cleaned.response_time_ms.mean()),
      "median":float(cleaned.response_time_ms.median()),"p90":float(cleaned.response_time_ms.quantile(.90)),
      "p95":float(cleaned.response_time_ms.quantile(.95)),"p99":float(cleaned.response_time_ms.quantile(.99)),
      "min":int(cleaned.response_time_ms.min()),"max":int(cleaned.response_time_ms.max())},
      "error_rate":float(cleaned.is_error.mean()),"4xx_rate":float(cleaned.is_4xx.mean()),
      "5xx_rate":float(cleaned.is_5xx.mean()),
      "requests_by_service":cleaned.service_name.value_counts().to_dict(),
      "requests_by_method":cleaned.method.value_counts().to_dict()}
    (out/"eda_metrics.json").write_text(json.dumps(metrics,indent=2,default=str))
    plots=[
      ("requests_by_service.png",lambda: cleaned.service_name.value_counts().plot(kind="bar",title="Requests by service",ylabel="Rows")),
      ("latency_distribution.png",lambda: cleaned.response_time_ms.plot(kind="hist",bins=25,title="Response-time distribution",xlabel="Milliseconds")),
      ("status_distribution.png",lambda: cleaned.status_code.value_counts().sort_index().plot(kind="bar",title="HTTP status distribution",ylabel="Rows"))
    ]
    for filename,draw in plots:
        plt.figure(); draw(); plt.tight_layout(); plt.savefig(out/filename,dpi=150); plt.close()
    print(json.dumps(metrics,indent=2,default=str))
if __name__=="__main__": main()
