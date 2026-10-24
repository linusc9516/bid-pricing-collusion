"""Build paper/main_apart.tex (the Apart submission template layout) from paper/main.tex: same content, template heading order and styles. Run from the repo root, then compile with xelatex."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paper_parts import load

P = load()
pre_keep, title_fn, abstract = P["preamble"], P["title_fn"], P["abstract"]
intro, setup, evalf, results = P["intro"], P["setup"], P["evalf"], P["results"]
disc_main, limitations, future, concl = P["disc_main"], P["limitations"], P["future"], P["concl"]
contrib, bib, related, code, llm = P["contrib"], P["bib"], P["related"], P["code"], P["llm"]
app = P["appendix"].replace("\\section{", "\\subsection{")

preamble = r"""\documentclass[10pt]{article}
\usepackage[letterpaper,margin=1in]{geometry}
\usepackage{graphicx,booktabs,amsmath,xcolor,enumitem,caption,microtype,tikz,colortbl,multirow,float}
\usepackage{newtxmath}
\usepackage[no-math]{fontspec}
\setmainfont{Times New Roman}
\usepackage{setspace}\setstretch{1.08}
\usepackage{titlesec,needspace}
\usepackage[section,above]{placeins}
\usepackage{flafter}
\definecolor{headtwo}{HTML}{434343}\definecolor{headthree}{HTML}{666666}
\titleformat{\section}{\needspace{6\baselineskip}\fontsize{14}{17}\selectfont\bfseries\color{headtwo}}{\thesection.}{0.35em}{}
\titleformat{\subsection}{\fontsize{13}{16}\selectfont\bfseries\color{headthree}}{\thesubsection}{0.5em}{}
\titlespacing*{\section}{0pt}{10pt}{2pt}
\titlespacing*{\subsection}{0pt}{10pt}{2pt}
\pagestyle{plain}
\setlength{\textfloatsep}{8pt plus 2pt minus 2pt}\setlength{\floatsep}{6pt plus 2pt minus 2pt}\setlength{\intextsep}{6pt plus 2pt minus 2pt}
"""
doc = preamble + pre_keep.replace("\\documentclass[10pt]{article}", "") + r"""
\DeclareCaptionFont{ninept}{\fontsize{9pt}{10.5pt}\selectfont}\captionsetup{font=ninept,skip=3pt}
\begin{document}

\noindent\rule{\textwidth}{1pt}
\begin{center}
{\fontsize{20}{25}\selectfont\bfseries CHANNELING COLLUSION: LLM BIDDERS RIG AUCTIONS WHEN ALLOWED TO TALK""" + title_fn + r"""}
\end{center}
\noindent\rule{\textwidth}{1pt}

\begin{center}
Linus C.\\ {[Affiliation]}\\ \texttt{[email]}

\vspace{0.8em}
\textbf{With}\\ Apart Research
\end{center}

\begin{center}{\fontsize{14}{17}\selectfont\bfseries Abstract}\end{center}
\begin{list}{}{\setlength{\leftmargin}{0.375in}\setlength{\rightmargin}{0.03in}}\item[]
""" + abstract + r"""
\end{list}

\section{Introduction}
""" + intro + r"""\section{Related Work}
""" + related + r"""\section{Methods}
\label{sec:methods}
\subsection{Setting up the Auction}
""" + setup + r"""\subsection{Evaluation Framework}
""" + evalf + r"""\section{Results}
""" + results + r"""\section{Discussion and Limitations}
""" + disc_main + r"""\subsection*{Limitations}
""" + limitations + r"""\subsection*{Future Work}
""" + future + r"""\section{Conclusion}
""" + concl + r"""\section*{Code and Data}
""" + code + r"""
\section*{Author Contributions}
""" + contrib + r"""
\renewcommand{\refname}{References}
""" + bib + r"""
\section*{Appendix}
\setcounter{subsection}{0}
\renewcommand{\thesubsection}{\Alph{subsection}}
\titleformat{\subsection}{\fontsize{13}{16}\selectfont\bfseries\color{headthree}}{\thesubsection.}{0.5em}{}
""" + app + r"""\section*{LLM Usage Statement}
""" + llm + "\\end{document}\n"
# Top-of-page floats can land above the heading of the section they belong to; prefer placing them in place.
doc = doc.replace("\\begin{figure}[t]", "\\begin{figure}[!htb]").replace("\\begin{table}[t]", "\\begin{table}[!htb]")
Path("paper/main_apart.tex").write_text(doc)
print("written", len(doc))
