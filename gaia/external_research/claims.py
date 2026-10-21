"""Closed, extractive claim catalog. No universal claims or generative interpretation."""
import re

from .schema import artifact, reference

PROPOSITIONS = {
    "PYTHON_GIL_CPU_THREADING": "GIL-enabled CPython documentation reports that only one thread executes Python code at a time.",
    "PYTHON_FREE_THREADED_BUILD": "CPython documentation reports support for a free-threaded build; local build availability is not established by this report.",
    "CUDA_MIN_COMPUTE_CAPABILITY": "This source reports a minimum CUDA compute capability for its stated software/version scope.",
}


def extract_claims(request, source, extracted, analysis_at):
    results = []
    for topic in request["payload"]["topics"]:
        for fragment in extracted["payload"]["fragments"]:
            if fragment["kind"] != "TEXT":
                continue
            text = fragment["text"]
            value, condition = None, "SOURCE_SCOPE"
            if topic == "PYTHON_GIL_CPU_THREADING":
                if re.search(r"only one thread can execute Python code at (?:once|a time)", text, re.I):
                    value, condition = True, "GIL_ENABLED"
                elif re.search(r"GIL.enabled CPython allows multiple threads to execute Python code simultaneously", text, re.I):
                    value, condition = False, "GIL_ENABLED"
            elif topic == "PYTHON_FREE_THREADED_BUILD":
                if (re.search(r"(?:starting with|as of) Python 3\.13", text, re.I) and re.search(r"free.thread", text, re.I)
                        or re.search(r"Python 3\.13 introduced.*free.thread", text, re.I)
                        or re.search(r"free.threaded builds can disable the GIL", text, re.I)):
                    value, condition = True, "BUILD_DEPENDENT"
            elif topic == "CUDA_MIN_COMPUTE_CAPABILITY":
                match = re.search(r"(?:requires?|minimum).*?compute capability\s*(?:>=|at least|of)?\s*(\d{1,2}\.\d{1,2})", text, re.I)
                if match:
                    value, condition = match.group(1), "VERSION_AND_HARDWARE_DEPENDENT"
            if value is None:
                continue
            payload = {"topic": topic, "normalized_proposition": PROPOSITIONS[topic], "reported_value": value,
                       "condition": condition, "source_ref": reference(source), "extraction_ref": reference(extracted),
                       "support": {"fragment_id": fragment["fragment_id"], "locator": fragment["locator"], "quote": text,
                                   "support_kind": "EXACT_NORMALIZED_QUOTE", "content_hash": source["payload"]["content_hash"]},
                       "source_class": source["payload"]["source_class"], "evidence_type": "EXTERNAL_DOCUMENT_REPORT",
                       "context": {"version": extracted["payload"]["version"], "version_basis": extracted["payload"]["version_basis"]},
                       "status": "REPORTED", "confidence": "VERY_LOW", "contradictions": [], "freshness": "UNASSESSED",
                       "locally_verified": False}
            results.append(artifact("CLAIM", payload, created_at=analysis_at,
                                    limitations=["Catalog match reports a source proposition, not local experimental verification or authority to apply it."]))
            break  # One bounded, cited proposition per topic/source; no repeated paragraphs as independent support.
    return results
