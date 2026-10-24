"""Build paper/main_acl.tex (ACL two-column layout, final mode) from paper/main.tex: same content, the Apart template's section order. Run from the repo root, then compile with pdflatex."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paper_parts import DROP_PREAMBLE, load

# acl.sty sets page, fonts, headings, captions, natbib and hyperref itself.
P = load(drop=DROP_PREAMBLE + ("\\usepackage[authoryear,round]{natbib}", "\\usepackage{hyperref}", "\\usepackage{titlesec}",
                               "\\hypersetup", "\\captionsetup", "\\setlength{\\parskip}"))

title = "Channeling Collusion: LLM Bidders Rig Auctions When Allowed To Talk"
thanks = P["title_fn"].replace("\\footnote{", "\\thanks{", 1)
# ACL abstracts are one paragraph without footnote marks in the title box; keep the code link as a footnote.
appendix = P["appendix"].replace("\\clearpage\n", "")

doc = r"""\documentclass[11pt]{article}
\usepackage[final]{acl}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{newtxtext,newtxmath}
\usepackage{inconsolata}
\usepackage{latexsym}
""" + P["preamble"] + r"""
\makeatletter
\def\section{\@startsection{section}{1}{\z@}{-1.4ex plus -0.4ex minus -.2ex}{0.9ex plus 0.2ex minus .2ex}{\large\bfseries\raggedright}}
\def\subsection{\@startsection{subsection}{2}{\z@}{-1.2ex plus -0.4ex minus -.2ex}{0.5ex plus .2ex}{\normalsize\bfseries\raggedright}}
\makeatother
\linespread{0.97}
\DeclareCaptionFont{ninept}{\fontsize{9pt}{10.5pt}\selectfont}\captionsetup{font=ninept,skip=4pt}
\setlength{\textfloatsep}{9pt plus 2pt minus 2pt}\setlength{\dbltextfloatsep}{9pt plus 2pt minus 2pt}
\setlength{\floatsep}{7pt plus 2pt minus 2pt}\setlength{\dblfloatsep}{7pt plus 2pt minus 2pt}\setlength{\intextsep}{7pt plus 2pt minus 2pt}
\title{""" + title + thanks + r"""}
\author{Linus C. \\ {[Affiliation]} \\ \texttt{[email]}}

\begin{document}
\maketitle

\begin{abstract}
""" + P["abstract"] + r"""
\end{abstract}

\section{Introduction}
""" + P["intro"] + r"""\section{Related Work}
""" + P["related"] + r"""\section{Methods}
\label{sec:methods}
\subsection{Setting up the Auction}
""" + P["setup"] + r"""\subsection{Evaluation Framework}
""" + P["evalf"] + r"""\section{Results}
""" + P["results"] + r"""\section{Discussion and Limitations}
""" + P["disc_main"] + r"""\subsection*{Limitations}
""" + P["limitations"] + r"""\subsection*{Future Work}
""" + P["future"] + r"""\section{Conclusion}
""" + P["concl"] + r"""\section*{Code and Data}
""" + P["code"] + r"""
\section*{Author Contributions}
""" + P["contrib"] + "\n" + P["bib"] + r"""
\appendix
""" + appendix + r"""\section*{LLM Usage Statement}
""" + P["llm"] + "\\end{document}\n"

# Two columns: floats sized to the full text width span both columns; the placebo plot and the stacked
# (_col) versions of the rounds and forest plots fit one column, so text runs beside them.
doc = doc.replace("\\includegraphics[width=0.62\\textwidth]{figures/fig_placebo.pdf}", "\\includegraphics[width=\\columnwidth]{figures/fig_placebo.pdf}")
for name in ("fig_rounds", "fig_contrasts", "fig_extensions"):
    doc = re.sub(r"\\includegraphics\[width=[^\]]*\]\{figures/" + name + r"\.pdf\}", r"\\includegraphics[width=\\columnwidth]{figures/" + name + "_col.pdf}", doc)

def _span(m: re.Match) -> str:
    body = m.group(2)
    return m.group(0) if "width=\\columnwidth" in body else "\\begin{figure*}[t]" + body + "\\end{figure*}"


doc = re.sub(r"\\begin\{figure\}(\[[^\]]*\])(.*?)\\end\{figure\}", _span, doc, flags=re.DOTALL)
doc = re.sub(r"\\begin\{table\}\[[^\]]*\]", r"\\begin{table*}[t]", doc).replace("\\end{table}", "\\end{table*}")

def _stack(m: re.Match) -> str:
    """One column cannot hold the aligned block with its row labels; give each outcome its own labelled display."""
    rows = [r.strip() for r in re.split(r"\\\\\[\d+pt\]|\\\\\s*\n", m.group(1)) if r.strip()]
    out = []
    for row in rows:
        label, eq = re.match(r"\\text\{(.+?)\}\\quad\s*(.*)", row, re.DOTALL).groups()
        out.append(label + ":\n\\[" + eq.replace("&=", "=").strip() + "\\]")
    return "\n".join(out)


doc = re.sub(r"\\begin\{align\*\}\n(\\text\{Collusion index.*?)\\end\{align\*\}", _stack, doc, flags=re.DOTALL)
Path("paper/main_acl.tex").write_text(doc)
print("written", len(doc))
