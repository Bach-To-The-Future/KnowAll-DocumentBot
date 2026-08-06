"""Can qwen3.5:4b run alongside the embedder in a 6 GiB container?

    python backend/scripts/stability_probe.py --phase all --minutes 30

RUNS ON THE HOST, not in a container: `docker stats` is the only honest source
of peak memory, and a process inside the container cannot see its own cgroup
peak reliably.

If this fails, the battery results are academic. 3.99 GiB resident was measured
with the generator ALONE and after nomic-embed-text had been idle-unloaded —
that is not the deployed state.

Phases, in dependency order:

  1 coexist    force BOTH models resident at once and record peak. Ollama
               unloads idle models, so this drives an embed and a generate
               concurrently rather than measuring after a pause.
  2 sustained  ingestion + querying together for --minutes, at realistic
               concurrency. Watches for OOM kills, restarts, latency drift and
               model SWAP THRASHING — the failure that never appears in a
               single-shot test.
  3 ceiling    num_ctx=8192 actually filled. KV cache scales with context, so
               the short-prompt measurement says nothing about the real
               profile. Post-C3 a prompt is 5 chunks with parent expansion.
  4 coldstart  container start -> first successful generation.
  5 pressure   deliberate over-subscription. Per finding #34's pattern the
               worst outcome is a SILENT EMPTY RESPONSE, so that is checked
               for by name rather than inferred from an error count.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

COMPOSE = ["docker", "compose"]
OLLAMA = "ollama"
LIMIT_GIB = 6.0


def sh(args: list[str], timeout: int = 900) -> str:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def mem_gib() -> float:
    out = sh(["docker", "stats", "--no-stream", "--format",
              "{{.Name}}\t{{.MemUsage}}", OLLAMA], timeout=60)
    if not out or "\t" not in out:
        return -1.0
    usage = out.split("\t")[1].split("/")[0].strip()
    value = float(usage.rstrip("GgMmKkIiBb"))
    if usage[-3:].upper().startswith("M"):
        value /= 1024
    elif usage[-3:].upper().startswith("K"):
        value /= 1024 * 1024
    return value


def loaded_models() -> list[str]:
    out = sh(COMPOSE + ["exec", "-T", "api", "python", "-c",
                        "import json,urllib.request;"
                        "print(json.dumps([m['name'] for m in json.load("
                        "urllib.request.urlopen('http://ollama:11434/api/ps'))"
                        ".get('models',[])]))"], timeout=120)
    for line in reversed(out.splitlines()):
        if line.strip().startswith("["):
            return list(json.loads(line.strip()))
    return []


def restarts() -> int:
    out = sh(["docker", "inspect", "-f", "{{.RestartCount}}", OLLAMA], timeout=60)
    return int(out) if out.isdigit() else -1


def oom_killed() -> bool:
    return sh(["docker", "inspect", "-f", "{{.State.OOMKilled}}", OLLAMA],
              timeout=60) == "true"


# --------------------------------------------------------------------------

REMOTE = r"""
import json, sys, time, urllib.request, urllib.error
kind, payload = sys.argv[1], json.loads(sys.argv[2])
url = "http://ollama:11434/api/" + ("embed" if kind == "embed" else "generate")
start = time.perf_counter()
try:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        body = json.load(r)
    dt = time.perf_counter() - start
    if kind == "embed":
        n = len(body.get("embeddings") or body.get("embedding") or [])
        print(json.dumps({"ok": True, "s": round(dt, 2), "n": n}))
    else:
        resp = body.get("response") or ""
        print(json.dumps({"ok": True, "s": round(dt, 2), "chars": len(resp),
                          "empty": len(resp.strip()) == 0,
                          "done_reason": body.get("done_reason"),
                          "eval_count": body.get("eval_count")}))
except Exception as e:
    print(json.dumps({"ok": False, "s": round(time.perf_counter() - start, 2),
                      "err": f"{type(e).__name__}: {e}"[:160]}))
"""


def call(kind: str, payload: dict, timeout: int = 900) -> dict:
    out = sh(COMPOSE + ["exec", "-T", "api", "python", "-c", REMOTE, kind,
                        json.dumps(payload)], timeout=timeout)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return dict(json.loads(line))
            except ValueError:
                continue
    return {"ok": False, "err": f"unparseable: {out[-160:]!r}"}


def gen(prompt: str, num_predict: int = 256) -> dict:
    return call("generate", {"model": "qwen3.5:4b", "prompt": prompt,
                             "stream": False, "think": False,
                             "options": {"num_ctx": 8192,
                                         "num_predict": num_predict,
                                         "temperature": 0.1}})


def emb(text: str) -> dict:
    return call("embed", {"model": "nomic-embed-text:latest", "input": text})


class Sampler(threading.Thread):
    """Peak memory has to be sampled while load is running, not after."""

    def __init__(self, interval: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.samples: list[float] = []
        self.interval = interval
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            value = mem_gib()
            if value > 0:
                self.samples.append(value)
            self._halt.wait(self.interval)

    def stop(self) -> tuple[float, float, int]:
        self._halt.set()
        self.join(timeout=10)
        if not self.samples:
            return -1.0, -1.0, 0
        return max(self.samples), statistics.median(self.samples), len(self.samples)


def report(label: str, peak: float, median: float, n: int) -> None:
    headroom = LIMIT_GIB - peak
    verdict = ("OK" if headroom > 1.0 else
               "TIGHT" if headroom > 0.3 else "CRITICAL")
    print(f"  {label:<26} peak={peak:.2f} GiB  median={median:.2f}  "
          f"headroom={headroom:.2f}  samples={n}  [{verdict}]")


# --------------------------------------------------------------------------

def phase_coexist() -> None:
    print("\n=== PHASE 1 — COEXISTENCE (both models resident at once) ===")
    print(f"  before: loaded={loaded_models()}  mem={mem_gib():.2f} GiB")
    sampler = Sampler(1.0)
    sampler.start()
    with ThreadPoolExecutor(max_workers=2) as pool:
        g = pool.submit(gen, "Summarise: records are retained for seven years.", 256)
        e = pool.submit(emb, "search_document: " + ("retention policy " * 200))
        gr, er = g.result(), e.result()
    time.sleep(2)
    during = loaded_models()
    peak, median, n = sampler.stop()
    print(f"  generate: {gr}")
    print(f"  embed   : {er}")
    print(f"  loaded during: {during}")
    report("both resident", peak, median, n)
    if len(during) < 2:
        print("  NOTE: fewer than 2 models reported loaded — Ollama may have")
        print("        serialised them. Peak is then NOT the coexistence peak.")


def phase_ceiling() -> None:
    print("\n=== PHASE 2 — CONTEXT CEILING (num_ctx=8192 actually filled) ===")
    # ~4 chars/token: 5 chunks at parent_char_budget=4000 is ~20000 chars.
    chunk = ("Retention Policy Notes. Records are retained for seven years from "
             "the date of creation. Disposal requires written authorisation "
             "from the records officer. ") * 40
    blocks = "\n\n".join(f"[{i}] (Source: doc{i}.txt)\n{chunk}" for i in range(1, 6))
    prompt = f"Context:\n{blocks}\n\nQuestion:\nHow long are records retained?"
    print(f"  prompt chars={len(prompt)}  (~{len(prompt) // 4} tokens est.)")
    sampler = Sampler(1.0)
    sampler.start()
    result = gen(prompt, 512)
    peak, median, n = sampler.stop()
    print(f"  result: {result}")
    report("full context", peak, median, n)
    if result.get("empty"):
        print("  SILENT EMPTY RESPONSE at full context — finding #34's pattern.")


def phase_sustained(minutes: int) -> None:
    print(f"\n=== PHASE 3 — SUSTAINED CONCURRENT LOAD ({minutes} min) ===")
    print("  querying + embedding together; watching for OOM, restarts,")
    print("  latency drift and model swap thrashing")
    start_restarts = restarts()
    sampler = Sampler(2.0)
    sampler.start()
    deadline = time.time() + minutes * 60
    lat: list[float] = []
    errors = empties = 0
    swaps = 0
    last_loaded: list[str] | None = None
    rounds = 0

    def one_query(i: int) -> dict:
        return gen(f"Question {i}: how long are records retained? "
                   f"Context: records are retained for seven years.", 128)

    while time.time() < deadline:
        rounds += 1
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(one_query, i) for i in range(3)]
            futures.append(pool.submit(emb, "search_document: policy " * 100))
            for f in futures:
                r = f.result()
                if not r.get("ok"):
                    errors += 1
                elif r.get("empty"):
                    empties += 1
                if r.get("ok") and "s" in r:
                    lat.append(r["s"])
        now = loaded_models()
        if last_loaded is not None and set(now) != set(last_loaded):
            swaps += 1
        last_loaded = now
        if rounds % 5 == 0:
            elapsed = minutes * 60 - (deadline - time.time())
            print(f"    {elapsed / 60:5.1f} min  rounds={rounds}  errors={errors}  "
                  f"empties={empties}  swaps={swaps}  mem={mem_gib():.2f} GiB")

    peak, median, n = sampler.stop()
    print(f"\n  rounds={rounds}  errors={errors}  silent-empties={empties}  "
          f"model-swaps={swaps}")
    print(f"  restarts: {start_restarts} -> {restarts()}   OOMKilled={oom_killed()}")
    report("sustained load", peak, median, n)
    if lat:
        half = len(lat) // 2
        first, second = lat[:half], lat[half:]
        print(f"  latency  first half median={statistics.median(first):.1f}s   "
              f"second half median={statistics.median(second):.1f}s")
        drift = statistics.median(second) - statistics.median(first)
        print(f"  drift    {drift:+.1f}s  "
              f"{'DEGRADING' if drift > 2 else 'stable'}")


def phase_coldstart() -> None:
    print("\n=== PHASE 4 — COLD START ===")
    subprocess.run(COMPOSE + ["restart", OLLAMA], capture_output=True, timeout=300)
    start = time.perf_counter()
    for attempt in range(60):
        result = gen("hi", 16)
        if result.get("ok"):
            print(f"  first successful generation after {time.perf_counter() - start:.1f}s "
                  f"({attempt + 1} attempt(s))")
            return
        time.sleep(5)
    print(f"  NO successful generation within {time.perf_counter() - start:.0f}s")


def phase_pressure() -> None:
    print("\n=== PHASE 5 — DELIBERATE OVER-SUBSCRIPTION ===")
    print("  8 concurrent full-context generations. Checking specifically for a")
    print("  SILENT EMPTY RESPONSE, which is the worst outcome (finding #34).")
    chunk = ("Records are retained for seven years from the date of creation. " * 60)
    prompt = (f"Context:\n[1] (Source: d.txt)\n{chunk}\n\nQuestion:\n"
              f"How long are records retained?")
    sampler = Sampler(1.0)
    sampler.start()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in [pool.submit(gen, prompt, 256)
                                        for _ in range(8)]]
    peak, median, n = sampler.stop()
    ok = sum(1 for r in results if r.get("ok"))
    empty = sum(1 for r in results if r.get("ok") and r.get("empty"))
    errs = [r.get("err") for r in results if not r.get("ok")]
    print(f"  succeeded={ok}/8   SILENT EMPTIES={empty}   errored={len(errs)}")
    for e in errs[:4]:
        print(f"    {e}")
    report("over-subscribed", peak, median, n)
    print(f"  restarts={restarts()}  OOMKilled={oom_killed()}")
    if empty:
        print("  WORST CASE CONFIRMED: requests succeeded and returned nothing.")
    elif errs:
        print("  Fails cleanly with an error rather than silently. Acceptable.")



# --------------------------------------------------------------------------

FULL_CTX_CHUNK = ("Retention Policy Notes. Records are retained for seven years "
                  "from the date of creation. Disposal requires written "
                  "authorisation from the records officer. ") * 40


def full_context_prompt(question: str = "How long are records retained?",
                        nonce: str = "") -> str:
    """~7,700 tokens: 5 chunks at parent_char_budget=4000, which is what
    post-C3 assembles for EVERY real query.

    `nonce` MUST vary per call. Ollama caches the KV prefill for a repeated
    prompt, so issuing the identical prompt N times measures cache hits, not
    inference. The first ladder run did exactly that and reported 19s at
    concurrency 2 against 218s at concurrency 1 — a nonsensical shape that was
    the cache, not the system. Real queries never repeat verbatim.
    """
    blocks = "\n\n".join(f"[{i}] (Source: doc{i}.txt)\n{FULL_CTX_CHUNK}"
                         for i in range(1, 6))
    return f"Context:\n{blocks}\n\nQuestion:\n{question}"


def phase_fullload(minutes: int) -> None:
    """The gap: sustained load AT FULL CONTEXT.

    4.62 GiB single-shot and 5.54 GiB sustained-short do not compose
    predictably — KV cache scales with context AND concurrency together, so
    the product is the thing to measure, not either factor.

    Latency is measured in the same run because it is plausibly the BINDING
    constraint ahead of memory: 189.66s single-shot against
    llm_read_timeout=300 leaves room for very little contention.
    """
    print(f"\n=== PHASE 6 - SUSTAINED FULL-CONTEXT LOAD ({minutes} min) ===")
    sample = full_context_prompt()
    print(f"  prompt chars={len(sample)} (~{len(sample) // 4} tokens est.)")
    print("  each call gets a UNIQUE prompt: a repeated one hits Ollama's "
          "prefix cache and measures the cache, not inference")
    print("  timeout budget: llm_read_timeout=300s")
    start_restarts = restarts()
    sampler = Sampler(2.0)
    sampler.start()
    deadline = time.time() + minutes * 60
    lat: list[float] = []
    errors = empties = timeouts = rounds = 0
    peak_concurrent_lat = 0.0

    while time.time() < deadline:
        rounds += 1
        # 2 concurrent full-context queries: the realistic contended case.
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [f.result() for f in [
                pool.submit(gen, full_context_prompt(
                    f"Round {rounds}-{j}: how long are records retained?",
                    nonce=f"[r{rounds}-{j} {time.time():.6f}] "), 256)
                for j in range(2)]]
        for r in results:
            if not r.get("ok"):
                errors += 1
            elif r.get("empty"):
                empties += 1
            if r.get("ok") and "s" in r:
                lat.append(r["s"])
                peak_concurrent_lat = max(peak_concurrent_lat, r["s"])
                if r["s"] > 300:
                    timeouts += 1
        print(f"    round {rounds}: "
              f"{[r.get('s') for r in results]}s  mem={mem_gib():.2f} GiB  "
              f"errors={errors} empties={empties} over300s={timeouts}")

    peak, median, n = sampler.stop()
    print(f"\n  rounds={rounds}  errors={errors}  silent-empties={empties}")
    print(f"  restarts: {start_restarts} -> {restarts()}   OOMKilled={oom_killed()}")
    report("sustained FULL context", peak, median, n)
    print(f"  CROSSES 6 GiB: {peak >= 6.0}")
    if lat:
        half = max(len(lat) // 2, 1)
        first, second = lat[:half], lat[half:] or lat[:half]
        print(f"  latency  median={statistics.median(lat):.1f}s  "
              f"max={max(lat):.1f}s  worst-concurrent={peak_concurrent_lat:.1f}s")
        print(f"  drift    first={statistics.median(first):.1f}s -> "
              f"second={statistics.median(second):.1f}s")
        print(f"  over llm_read_timeout=300s: {timeouts}/{len(lat)}")


def phase_concurrency_ladder() -> None:
    """At what concurrency does full-context latency cross llm_read_timeout?

    Reported as the crossing LEVEL, because that is the operational limit —
    max_concurrent_queries=20 is meaningless if 3 exceeds the timeout.
    """
    print("\n=== PHASE 7 — CONCURRENCY LADDER vs llm_read_timeout=300s ===")
    crossed_at = None
    for level in (1, 2, 3, 4):
        sampler = Sampler(1.0)
        sampler.start()
        with ThreadPoolExecutor(max_workers=level) as pool:
            results = [f.result() for f in [
                pool.submit(gen, full_context_prompt(
                    f"Query {level}-{j}: how long are records retained?",
                    nonce=f"[run {level}-{j} {time.time():.6f}] "), 256)
                for j in range(level)]]
        peak, _, _ = sampler.stop()
        lat = [r["s"] for r in results if r.get("ok") and "s" in r]
        errs = sum(1 for r in results if not r.get("ok"))
        empt = sum(1 for r in results if r.get("ok") and r.get("empty"))
        worst = max(lat) if lat else -1
        flag = ""
        if worst > 300:
            flag = "   <-- EXCEEDS llm_read_timeout"
            crossed_at = crossed_at or level
        print(f"  concurrency={level}  worst={worst:6.1f}s  "
              f"median={statistics.median(lat) if lat else -1:6.1f}s  "
              f"peak_mem={peak:.2f} GiB  errors={errs} empties={empt}{flag}")
    print(f"\n  crosses the 300s timeout at concurrency: "
          f"{crossed_at if crossed_at else 'not within 4'}")
    print("  max_concurrent_queries=20 is the configured admission limit; the")
    print("  measured limit is whatever this says.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", default="all",
                        choices=["all", "coexist", "ceiling", "sustained",
                                 "coldstart", "pressure", "fullload",
                                 "ladder"])
    parser.add_argument("--minutes", type=int, default=30)
    args = parser.parse_args()

    print(f"container limit: {LIMIT_GIB} GiB   baseline mem: {mem_gib():.2f} GiB")
    if args.phase in ("all", "coexist"):
        phase_coexist()
    if args.phase in ("all", "ceiling"):
        phase_ceiling()
    if args.phase in ("all", "sustained"):
        phase_sustained(args.minutes)
    if args.phase in ("all", "pressure"):
        phase_pressure()
    if args.phase in ("all", "fullload"):
        phase_fullload(args.minutes)
    if args.phase in ("all", "ladder"):
        phase_concurrency_ladder()
    if args.phase in ("all", "coldstart"):
        phase_coldstart()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
