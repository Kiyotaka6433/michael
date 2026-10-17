"""Plain data objects passed between pipeline stages."""
import hashlib
from dataclasses import asdict, dataclass, field


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf8")).hexdigest()


@dataclass
class Source:
    kind: str                 # wikipedia | arxiv | openalex | web | pdf | vault
    title: str
    url: str                  # URL, or file path for pdf/vault
    text: str
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = sha(f"{self.kind}|{self.url}")[:16]


@dataclass
class Chunk:
    source_id: str
    kind: str
    title: str
    url: str
    text: str
    start: int                # character offsets inside the source text
    end: int
    heading: str = ""         # section heading (vault) or "p. N" (pdf)
    id: str = ""
    label: str = ""           # p1..pN once selected as evidence
    score: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = sha(f"{self.source_id}|{self.start}|{self.text}")[:16]

    @property
    def link(self) -> str:
        if self.kind == "vault":
            stem = self.url.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".md")
            return f"[[{stem}#{self.heading}]]" if self.heading and self.heading != stem else f"[[{stem}]]"
        return f"[{self.title}]({self.url})"


@dataclass
class Claim:
    index: int
    sentence: str
    citations: list = field(default_factory=list)   # evidence labels, e.g. ["p1", "p3"]
    status: str = "pending"                          # SUPPORTED | PARTIAL | UNSUPPORTED | REMOVED
    rounds: int = 0


@dataclass
class Verdict:
    claim_index: int
    label: str                # SUPPORTED | PARTIAL | UNSUPPORTED
    chunk_id: str = ""
    evidence_label: str = ""
    quote: str = ""
    quote_start: int = -1     # offsets of the quote inside the chunk text
    quote_end: int = -1
    entailment: float = 0.0
    contradiction: float = 0.0
    in_context: bool = False  # judged together with its paragraph (e.g. "our model" -> "the Transformer")
    math: str = ""            # formulas/numbers checked by ophaniel: match | mismatch | unchecked

    def to_dict(self):
        return asdict(self)
