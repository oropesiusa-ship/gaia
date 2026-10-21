"""Audited deterministic chat formatting, separate from inference runtime APIs."""
from ..provenance import digest


def format_prompt(text, family):
    # Both qualified families publish ChatML templates. No model-provided Jinja
    # or executable template is evaluated in the GAIA process.
    if family == 'gemma4':
        return '<bos><|turn>system\nYou are a local text processor. Follow the requested output format exactly. You have no tools or authority.<turn|>\n<|turn>user\n'+text+'<turn|>\n<|turn>model\n'
    if family not in ("qwen3", "smollm3"):
        raise ValueError("Model template requires explicit qualification")
    system = "You are a local text processor. Follow the user's output format exactly. You have no tools or authority. /no_think"
    return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{text} /no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def identity(family):
    return digest({"family": family, "template_version": "audited_chatml_no_think_v1", "empty_prompt": format_prompt("", family)})
