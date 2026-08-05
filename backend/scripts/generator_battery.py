"""The exact battery that established the 1B constraint, re-runnable on any
generation model.

    docker compose exec -e OLLAMA_LLM_MODEL=<tag> api \\
        python scripts/generator_battery.py

Changing `llm_model` invalidates F31, D3, D4, D6 and F33 and every full-mode
baseline — `eval/compare.py` already hard-fails on it in full mode, which is
correct. So the four suites below are reproduced UNCHANGED from the runs that
produced those findings, and the numbers are directly comparable:

  F31  the 4 near-miss probes             does rule 3 fire?
  D3   controls 1-3                       is the verdict token still fixed?
                                          Control 2 (flipped labels) decides it.
  D6   15 positives / 5 negatives         emission rate and match-given-quote,
                                          reported SEPARATELY
  F33  3 prompt variants                  stripped / shipped / with rule 5

Latency and memory are recorded alongside: a grounding mechanism that works but
triples response time is a tradeoff for the maintainer, not a free win.

WHAT THIS CANNOT TELL YOU: finding #27 and the cross-encoder half of finding
#31 — that a cross-encoder scores topical relevance rather than answer
presence — live in bge-reranker-base and are untouched by the generator. They
stay open whatever this reports.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging  # noqa: E402

logging.disable(logging.INFO)

from core.config import get_settings  # noqa: E402
from services import grounding  # noqa: E402
from services.container import build_container  # noqa: E402
from services.query import (  # noqa: E402
    NO_ANSWER_MESSAGE,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_WITH_SUPPORT,
)

STRIPPED_PROMPT = """You are a document question-answering assistant.
Rules:
1. Answer using ONLY the numbered context passages provided by the user.
2. Cite the passage number(s) in square brackets, e.g. [1] or [1][3], for every factual claim."""

VERIFY_SYSTEM = (
    "You check whether a statement is supported by a passage. Answer with "
    "exactly one word: YES if the passage states or directly implies the "
    "statement, NO if it does not. Do not explain."
)

RETENTION = ("Retention Policy Notes. Records are retained for seven years from "
             "the date of creation. Disposal requires written authorisation from "
             "the records officer.")
HANDBOOK = ("Field Handbook. Reporting. Incidents must be reported within 24 hours "
            "of discovery. Escalation. Unresolved incidents escalate to the duty "
            "supervisor after 72 hours.")
SLA = ("Service Level Agreement. Priority one tickets are acknowledged within 15 "
       "minutes. Credits apply when uptime falls below 99.5 percent.")
OPS = ("Operations Manual. Access Control. Badge access is revoked automatically "
       "after 30 days of inactivity. Maintenance Windows. Scheduled maintenance "
       "occurs on the second Sunday monthly.")
AVIS = ("AVIS ARCHIVE. Le plafond de la subvention est de 75000 dollars. "
        "Les demandes doivent etre soumises avant le 31 mars.")
FACILITIES = ("Facilities Bulletin. Lobby renovations continue through the end of "
              "the fiscal year. Parking permits are reissued each September.")

POSITIVES = [
    ("en", "How long are records retained?", RETENTION, "seven"),
    ("en", "Who authorises disposal?", RETENTION, "records officer"),
    ("en", "Within how long must an incident be reported?", HANDBOOK, "24"),
    ("en", "After how long does an incident escalate?", HANDBOOK, "72"),
    ("en", "Who do unresolved incidents escalate to?", HANDBOOK, "supervisor"),
    ("en", "How quickly are priority one tickets acknowledged?", SLA, "15"),
    ("en", "When do credits apply?", SLA, "99.5"),
    ("en", "When is badge access revoked?", OPS, "30"),
    ("en", "When does scheduled maintenance occur?", OPS, "Sunday"),
    ("en", "How often are parking permits reissued?", FACILITIES, "September"),
    ("en", "What is happening in the lobby?", FACILITIES, "renovation"),
    ("fr", "Quel est le plafond de la subvention ?", AVIS, "75"),
    ("fr", "Avant quelle date les demandes doivent-elles etre soumises ?", AVIS, "31 mars"),
    ("en", "How long are records kept and who signs off on destroying them?", RETENTION, "seven"),
    ("en", "What is the reporting deadline and what happens after 72 hours?", HANDBOOK, "24"),
]

NEAR_MISS = [
    ("en", "Who can authorise an exception to the seven-year retention period?", RETENTION),
    ("en", "What happens to an incident that is still unresolved after the duty "
           "supervisor has been notified?", HANDBOOK),
    ("en", "What penalty applies when uptime falls below 95 percent?", SLA),
    ("fr", "Quel montant est accorde aux demandes soumises apres le 31 mars ?", AVIS),
]

D3_CASES = [
    # (label, passage, claim, should_accept)
    ("C1 trivial identical", "The sky is blue.", "The sky is blue.", True),
    ("C1 verbatim sentence", RETENTION,
     "Records are retained for seven years from the date of creation.", True),
    ("C2 flipped: supported", RETENTION, "Records are retained for seven years.", True),
    ("C2 flipped: contradicted", RETENTION, "Records are retained for two years.", False),
    ("NEG benchmark inversion", AVIS,
     "Le montant accorde aux demandes soumises apres le 31 mars est de 75000 dollars.", False),
]


def timed_complete(container, system: str, prompt: str) -> tuple[str, float]:
    start = time.perf_counter()
    out = container.query._llm.complete(prompt=prompt, system_prompt=system)
    return out.strip(), time.perf_counter() - start


def ctx(passage: str, question: str) -> str:
    return f"Context:\n[1] (Source: test)\n{passage}\n\nQuestion:\n{question}"


def main() -> int:
    settings = get_settings()
    container = build_container(settings)
    print(f"MODEL: {settings.llm_model}")
    print(f"num_ctx={settings.llm_num_ctx}  num_predict={settings.llm_num_predict}  "
          f"temperature={settings.llm_temperature}\n")
    latencies: list[float] = []

    # ---- F31: does rule 3 fire on near-misses? --------------------------
    print("=== F31 — rule 3 on 4 near-miss probes (1B: 0/4 declined) ===")
    declined = 0
    for lang, question, passage in NEAR_MISS:
        out, dt = timed_complete(container, SYSTEM_PROMPT, ctx(passage, question))
        latencies.append(dt)
        ok = NO_ANSWER_MESSAGE.rstrip(".").lower() in out.lower()
        declined += ok
        print(f"  [{lang}] {'DECLINED' if ok else 'ANSWERED'}  ({dt:5.1f}s)  {question[:52]}")
        if not ok:
            print(f"        {out[:130]!r}")
    print(f"  -> declined {declined}/4")

    # ---- D3: is the verdict token fixed? --------------------------------
    print("\n=== D3 — controls 1-3 (1B: fixed 'NO', 0/16 accepted) ===")
    correct = 0
    for label, passage, claim, should_accept in D3_CASES:
        system = VERIFY_SYSTEM
        prompt = (f"Passage:\n{passage}\n\nStatement:\n{claim}\n\n"
                  f"Is the statement supported by the passage? Answer YES or NO.")
        if label.startswith("C2"):
            system = ("You check whether a statement CONTRADICTS a passage. Answer "
                      "with exactly one word: YES if the statement contradicts the "
                      "passage, NO if the passage supports it. Do not explain.")
            prompt = (f"Passage:\n{passage}\n\nStatement:\n{claim}\n\n"
                      f"Does the statement contradict the passage? Answer YES or NO.")
        out, dt = timed_complete(container, system, prompt)
        latencies.append(dt)
        said_yes = out.upper().startswith("YES")
        # C2 inverts the meaning of YES.
        accepted = (not said_yes) if label.startswith("C2") else said_yes
        ok = accepted == should_accept
        correct += ok
        print(f"  {'ok  ' if ok else 'WRONG'} ({dt:5.1f}s) said={out[:12]!r:<14} {label}")
    print(f"  -> {correct}/{len(D3_CASES)} correct. Control 2 answering YES at least "
          f"once is the decisive signal.")

    # ---- D6: emission and match, reported separately --------------------
    print("\n=== D6 — quote emission and match (1B: emission 3/15, match 0/3) ===")
    emitted = matched = 0
    for lang, question, passage, _ in POSITIVES:
        citations = [{"index": 1, "text": passage}]
        out, dt = timed_complete(container, SYSTEM_PROMPT_WITH_SUPPORT,
                                 ctx(passage, question))
        latencies.append(dt)
        result = grounding.check(out, citations)
        emitted += result.emitted_quotes
        matched += result.supported
        print(f"  [{lang}] quoted={str(result.emitted_quotes):<5} "
              f"supported={str(result.supported):<5} ({dt:5.1f}s) {result.reason:<16} "
              f"{question[:40]}")
    print(f"  -> EMISSION {emitted}/15   MATCH-GIVEN-QUOTE "
          f"{matched}/{emitted if emitted else '0'}   KEPT {matched}/15")

    # ---- F33: three prompt variants -------------------------------------
    print("\n=== F33 — prompt variants (1B: stripped 15/15, shipped 12/15, rule5 2/15) ===")
    for name, system in (("stripped", STRIPPED_PROMPT),
                         ("shipped ", SYSTEM_PROMPT),
                         ("rule5   ", SYSTEM_PROMPT_WITH_SUPPORT)):
        answered = 0
        for lang, question, passage, _ in POSITIVES:
            out, dt = timed_complete(container, system, ctx(passage, question))
            latencies.append(dt)
            if NO_ANSWER_MESSAGE.rstrip(".").lower() not in out.lower():
                answered += 1
        print(f"  {name}  answered {answered}/15")

    print("\n=== LATENCY (CPU) ===")
    latencies.sort()
    n = len(latencies)
    print(f"  n={n}  min={latencies[0]:.1f}s  median={latencies[n // 2]:.1f}s  "
          f"p95={latencies[int(n * 0.95)]:.1f}s  max={latencies[-1]:.1f}s")
    print("  Compare against the 1B baseline before calling any recovery free.")
    print("\n  Memory: run `docker stats --no-stream` against the OLLAMA container.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
