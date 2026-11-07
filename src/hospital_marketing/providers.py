import re


class ProviderConfigurationError(ValueError):
    pass


class ProviderRequestError(RuntimeError):
    pass


def _redact_openai_key_error(message: str) -> str:
    match = re.search(r"(?i)Incorrect API key provided:\s*\S+", message)
    if match is None:
        return message
    credential = match.group(0).rsplit(maxsplit=1)[-1].strip(".,;:!?\"'()[]{}")
    end = match.end()
    if credential.lower().startswith("sk-") and credential.endswith("*"):
        suffix = re.match(r"\s+([A-Za-z0-9]{4})(?=$|\s|[^A-Za-z0-9_])", message[end:])
        if suffix is not None:
            end += suffix.end()
    return f"{message[:match.start()]}[REDACTED]{message[end:]}"


def _redact_masked_tokens(message: str) -> str:
    tokens = message.split()
    redacted = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.count("*") < 3:
            redacted.append(token)
            index += 1
            continue
        redacted.append("[REDACTED]")
        key_prefix = token.strip(".,;:!?\"'()[]{}")
        if key_prefix.lower().startswith("sk-") and key_prefix.endswith("*") and index + 1 < len(tokens):
            suffix = tokens[index + 1].strip(".,;:!?\"'()[]{}")
            if len(suffix) == 4 and suffix.isalnum():
                index += 1
        index += 1
    return " ".join(redacted)


def sanitize_provider_error_message(message: str, api_key: str = "") -> str:
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = " ".join(message.split())
    message = re.sub(
        r"(?i)\b(?:authorization|x-api-key|x-goog-api-key|anthropic-version)\s*[:=]\s*(?:bearer\s+)?\S+",
        "[REDACTED HEADER]",
        message,
    )
    message = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [REDACTED]", message)
    message = _redact_openai_key_error(message)
    return _redact_masked_tokens(message)
