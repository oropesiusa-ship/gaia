"""Human-readable factual report; contains no diagnosis or advice."""


def render(value, comparison=None):
    facts = value["sections"]["facts"]
    host, runtime = facts["host"], facts["runtime"]
    cpu, ram = host.get("cpu", {}), host.get("ram", {})
    memory = ram.get("total_bytes")
    workload = value["sections"]["measurements"]["workload"]
    lines = ["GAIA SYSTEM OBSERVATION", "Observation " + value["observation_id"],
             "", "HOST", f"CPU: {cpu.get('model')} · logical={cpu.get('logical_cores')} · physical={cpu.get('physical_cores')}",
             f"RAM: {memory / 2**30:.2f} GiB" if memory else "RAM: UNAVAILABLE",
             f"GPU: {facts['gpu'].get('status')} · devices={facts['gpu'].get('device_count')} · campaign=FROZEN",
             "", "RUNTIME", f"Python: {runtime.get('python', {}).get('version')}",
             f"NumPy: {runtime.get('libraries', {}).get('numpy')}",
             f"bwrap: present={runtime.get('sandbox', {}).get('present')} · verified={runtime.get('sandbox', {}).get('verified')}",
             "", "CAPABILITIES"]
    lines += [f"{c['name']}: {c['status']}" for c in value["sections"]["capabilities"]]
    lines += ["", "COMPONENTS"] + [f"{c['component_id']}: {c['status']} · {c['source_hash'][:12]}" for c in facts["components"]]
    resources = value["sections"]["measurements"]["resources"]
    lines += ["", "RESOURCES"]
    for name in ("process_rss_bytes", "process_lifetime_peak_rss_bytes", "system_ram_available_bytes",
                 "system_cpu_utilization_percent", "filesystem_free_bytes"):
        metric = resources.get("statistics", {}).get(name, {})
        lines.append(f"{name}: median={metric.get('median')} · {metric.get('stability', 'UNAVAILABLE')}")
    lines += ["", "WORKLOAD", f"numpy_mlp: {workload['status']} · successful samples={workload.get('success_count', 0)}",
              "", "STABILITY"]
    for name, metric in workload.get("statistics", {}).items():
        lines.append(f"{name}: median={metric['median']} · CV={metric['coefficient_of_variation']} · {metric['stability']}")
    lines += ["", "COST", str(value["sections"]["context"]["cost"]),
              "Observation hash: " + value["observation_hash"]]
    if comparison:
        lines += ["", "CHANGES VS PREVIOUS", render_comparison(comparison)]
    return "\n".join(lines)


def render_comparison(value):
    lines = [f"{value['a']} vs {value['b']}",
             f"hardware_changed={value['hardware_changed']} runtime_changed={value['runtime_changed']} source_changed={value['source_changed']}",
             f"capability_changed={value['capability_changed']} fields_changed={len(value['fields'])}"]
    for metric in value["measurements"]:
        relative = metric["relative_change"]
        delta = f"{relative:+.2%}" if relative is not None else "unavailable"
        lines.append(f"{metric['metric']}: {delta} · {metric['classification']}")
    return "\n".join(lines)
