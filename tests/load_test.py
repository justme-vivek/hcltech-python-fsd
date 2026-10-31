"""Automated Gateway Load Test

Executes concurrent traffic through the Nginx HTTPS gateway,
measuring RPS, p50, p95, p99 latencies, and error rates.
"""
import os, sys, time, ssl, statistics, concurrent.futures
import httpx
from shared.security import create_token

GATEWAY_URL = os.getenv("GATEWAY_URL", "https://gateway:443")
CA_CERT = os.getenv("MTLS_CA_FILE", "/certs/ca.crt")

def run_load_test(concurrency=10, total_requests=100):
    ctx = ssl.create_default_context(cafile=CA_CERT)
    admin_token = create_token("admin-load-test", "admin", 60)
    customer_token = create_token("customer-load-test", "customer", 60)
    
    headers = {"Authorization": f"Bearer {customer_token}"}
    status_counts = {}
    latencies = []
    errors = 0
    start_time = time.time()

    def send_request(idx):
        t0 = time.perf_counter()
        try:
            endpoint = "/products?page=1&size=5" if idx % 2 == 0 else "/auth/me"
            with httpx.Client(base_url=GATEWAY_URL, verify=ctx, timeout=10.0) as client:
                resp = client.get(endpoint, headers=headers)
                t1 = time.perf_counter()
                elapsed_ms = (t1 - t0) * 1000.0
                return elapsed_ms, resp.status_code
        except Exception as e:
            t1 = time.perf_counter()
            return (t1 - t0) * 1000.0, 599

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(send_request, i) for i in range(total_requests)]
        for f in concurrent.futures.as_completed(futures):
            dur, code = f.result()
            latencies.append(dur)
            status_counts[code] = status_counts.get(code, 0) + 1
            if code >= 500 and code != 503:  # Ignore expected gateway throttling.
                errors += 1

    total_time = time.time() - start_time
    rps = total_requests / total_time if total_time > 0 else 0
    latencies.sort()
    
    def percentile(p):
        idx = int(len(latencies) * p)
        return latencies[min(idx, len(latencies) - 1)]

    p50 = percentile(0.50)
    p90 = percentile(0.90)
    p95 = percentile(0.95)
    p99 = percentile(0.99)
    min_lat = min(latencies)
    max_lat = max(latencies)
    avg_lat = statistics.mean(latencies)
    error_rate = (errors / total_requests) * 100.0

    print("=== GATEWAY LOAD TEST RESULTS ===")
    print(f"Total Requests:      {total_requests}")
    print(f"Concurrency:         {concurrency}")
    print(f"Duration:            {total_time:.2f} s")
    print(f"Throughput (RPS):    {rps:.2f} req/s")
    print(f"Error Rate:          {error_rate:.2f}% ({errors}/{total_requests})")
    print(f"Min Latency:         {min_lat:.2f} ms")
    print(f"Average Latency:     {avg_lat:.2f} ms")
    print(f"Median (p50):        {p50:.2f} ms")
    print(f"p90 Latency:         {p90:.2f} ms")
    print(f"p95 Latency:         {p95:.2f} ms")
    print(f"p99 Latency:         {p99:.2f} ms")
    print(f"Max Latency:         {max_lat:.2f} ms")
    print("=================================")

    return {
        "total_requests": total_requests,
        "concurrency": concurrency,
        "duration_seconds": round(total_time, 2),
        "rps": round(rps, 2),
        "error_rate_pct": round(error_rate, 2),
        "min_ms": round(min_lat, 2),
        "avg_ms": round(avg_lat, 2),
        "p50_ms": round(p50, 2),
        "p90_ms": round(p90, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "max_ms": round(max_lat, 2)
    }

if __name__ == "__main__":
    run_load_test(concurrency=10, total_requests=100)
