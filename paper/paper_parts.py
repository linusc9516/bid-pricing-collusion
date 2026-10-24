"""Slice paper/main.tex into its parts, unchanged, for the submission layouts (build_apart.py, build_acl.py)."""
import re
from pathlib import Path

DROP_PREAMBLE = ("\\documentclass", "\\usepackage[T1]", "\\usepackage[utf8]", "\\usepackage{newtx", "\\usepackage[letterpaper",
                 "\\pagestyle", "\\renewcommand{\\headrulewidth", "\\titleformat", "\\titlespacing")


def load(path: Path = Path("paper/main.tex"), drop: tuple[str, ...] = DROP_PREAMBLE) -> dict[str, str]:
    """Return the preamble lines kept (macros, colours, boxes) and each section's body, keyed by name."""
    src = path.read_text()

    def between(a: str, b: str) -> str:
        i = src.index(a)
        j = src.index(b, i + len(a))
        return src[i + len(a):j]

    pre = src[:src.index(r"\begin{document}")]
    disc = between("\\section{Discussion and Limitations}\n", "\\section{Conclusion}")
    lim_i = disc.index("\\para{Limitations.} ")
    fut_i = disc.index("\\para{Future work.} ")
    return {
        "preamble": "\n".join(line for line in pre.splitlines() if not line.startswith(drop)),
        "title_fn": re.search(r"When Allowed To Talk(\\footnote\{.*?\})\}\n", src).group(1),
        "abstract": between("\\begin{quote}\n", "\\end{quote}").strip(),
        "intro": between("\\section{Introduction}\n", "\\section{Setting up the Auction}"),
        "setup": between("\\section{Setting up the Auction}\n", "\\section{Evaluation Framework}"),
        "evalf": between("\\section{Evaluation Framework}\n", "\\section{Experiments and Analysis}"),
        "results": between("\\section{Experiments and Analysis}\n", "\\section{Discussion and Limitations}"),
        "disc_main": disc[:lim_i],
        "limitations": disc[lim_i + len("\\para{Limitations.} "):fut_i],
        "future": disc[fut_i + len("\\para{Future work.} "):],
        "concl": between("\\section{Conclusion}\n", "\\section*{Author Contributions}"),
        "contrib": between("\\section*{Author Contributions}\n", "\\begin{thebibliography}"),
        "bib": "\\begin{thebibliography}" + between("\\begin{thebibliography}", "\\end{thebibliography}") + "\\end{thebibliography}\n",
        "related": between("\\section{Related Work}\n", "\\section{Metric Definitions and Tests}"),
        "appendix": "\\section{Metric Definitions and Tests}" + between("\\section{Metric Definitions and Tests}", "\\section{Code and Data}"),
        "code": between("\\section{Code and Data}\n", "\\section{LLM Usage Statement}"),
        "llm": between("\\section{LLM Usage Statement}\n", "\\end{document}"),
    }
