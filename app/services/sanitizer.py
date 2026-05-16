"""Output sanitization — strip XSS vectors and control chars from LLM responses."""
import re


def sanitize_llm_output(text: str) -> str:
    """Strip control characters and XSS vectors from a single LLM output string."""
    # Remove ASCII control chars except tab (9), newline (10), carriage return (13)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Strip <script> blocks (including multiline)
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    # Strip javascript: URIs
    text = re.sub(r'javascript\s*:', '', text, flags=re.IGNORECASE)
    return text


def sanitize_result(obj):
    """Recursively sanitize all string values in a nested dict/list structure."""
    if isinstance(obj, str):
        return sanitize_llm_output(obj)
    if isinstance(obj, dict):
        return {k: sanitize_result(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_result(i) for i in obj]
    return obj
