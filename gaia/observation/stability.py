"""Descriptive statistics and explicit conservative stability criteria."""
import math
import statistics


def summarize(samples, cv_threshold=0.10, minimum=3):
    samples = [float(x) for x in samples if x is not None and math.isfinite(x)]
    result = {"samples": samples, "count": len(samples), "mean": None, "median": None,
              "min": None, "max": None, "standard_deviation": None, "coefficient_of_variation": None,
              "stability": "INSUFFICIENT_DATA", "criteria": {"minimum_samples": minimum, "max_cv": cv_threshold}}
    if not samples:
        return result
    mean = statistics.mean(samples)
    sd = statistics.stdev(samples) if len(samples) > 1 else None
    cv = sd / abs(mean) if sd is not None and mean != 0 else 0.0 if sd == 0 else None
    result.update(mean=mean, median=statistics.median(samples), min=min(samples), max=max(samples),
                  standard_deviation=sd, coefficient_of_variation=cv)
    if len(samples) >= minimum and cv is not None:
        result["stability"] = "STABLE" if cv <= cv_threshold else "NOISY"
    return result
