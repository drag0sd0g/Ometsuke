"""The local model client. Runs against pinned open weights on this machine; nothing
here calls a paid API, and nothing here should acquire the ability to.

Three things this module exists to get right, each of which is a way a long unattended
run can quietly produce a wrong number rather than an error:

  1. **The weights are part of the run's identity.** `name` carries the blob digest, not
     just the tag, because tags move. Two runs against different weights must not be able
     to collide in `config_hash`.
  2. **Thinking is suppressed explicitly.** The base model is a reasoning model. Left to
     itself on a bounded output budget it spends the whole allowance thinking and returns
     an empty response — which parses as a failure, not as a verdict, so a whole sweep
     can come back empty. `think=False` is sent on every call and recorded in the config.
  3. **Timeouts are generous by default.** A filing at the observed maximum is ~62k
     tokens, which is roughly 80 seconds of prefill before a single token is generated. A
     default timeout tuned for chat would fail systematically on long filings — and
     because long filings are not a random subset, the surviving score would be computed
     over easier documents than the one advertised.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .model import ModelResponse

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TAG = "ometsuke-eval"
# ~80s of prefill at the observed maximum filing size, plus generation and headroom.
DEFAULT_TIMEOUT_S = 600

_FROM_BLOB = re.compile(r"^FROM\s+.*/blobs/(sha256[-:][0-9a-f]{64})\s*$", re.M)


class OllamaError(RuntimeError):
    """The server could not be reached, or refused the request."""


def _post(host: str, path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{host}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise OllamaError(f"{path} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"cannot reach the model server at {host} ({exc.reason}). "
            "Is the ollama service running?"
        ) from exc


def weights_digest(tag: str, host: str = DEFAULT_HOST, timeout: float = 30) -> str:
    """The SHA-256 of the weights behind a tag.

    This is the identity that matters. A tag is a mutable pointer; rebuilding a Modelfile
    against different base weights reuses the name and silently changes what a run
    measured.
    """
    shown = _post(host, "/api/show", {"name": tag}, timeout)
    match = _FROM_BLOB.search(shown.get("modelfile", ""))
    if not match:
        raise OllamaError(
            f"could not determine the weights digest for {tag!r}. "
            "A run whose weights cannot be identified is not reproducible, so this is "
            "refused rather than recorded as unknown."
        )
    return match.group(1).replace("sha256:", "sha256-")


class OllamaModel:
    """A local model behind the `Model` protocol.

    `name` is `<tag>@<digest>`, so the run config distinguishes weights as well as tags.
    """

    def __init__(
        self,
        tag: str = DEFAULT_TAG,
        host: str = DEFAULT_HOST,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        think: bool = False,
        options: dict[str, Any] | None = None,
        digest: str | None = None,
    ) -> None:
        self.tag = tag
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.think = think
        self.options = dict(options or {})
        self.digest = digest or weights_digest(tag, self.host)
        self.name = f"{tag}@{self.digest}"

    def config(self) -> dict[str, Any]:
        """What must be recorded for this run to mean anything later.

        Sampling parameters live in the Modelfile, so they are covered by the digest of
        the model rather than repeated here; what this adds is everything the *client*
        decides per call.
        """
        return {
            "model_tag": self.tag,
            "weights_digest": self.digest,
            "think": self.think,
            "client_options": self.options,
        }

    def complete(self, prompt: str) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.tag,
            "prompt": prompt,
            "stream": False,
            "think": self.think,
        }
        if self.options:
            payload["options"] = self.options

        body = _post(self.host, "/api/generate", payload, self.timeout_s)
        if "error" in body:
            raise OllamaError(f"generate failed: {body['error']}")

        return ModelResponse(
            text=body.get("response") or "",
            input_tokens=int(body.get("prompt_eval_count") or 0),
            output_tokens=int(body.get("eval_count") or 0),
            # Ollama reuses the KV cache across shared prefixes but does not report it.
            # Reporting anything but zero here would be a number we made up.
            cache_read_tokens=0,
            latency_ms=int((body.get("total_duration") or 0) / 1e6),
            stop_reason=str(body.get("done_reason") or "unknown"),
        )
