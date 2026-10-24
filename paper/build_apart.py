"""Build paper/main_apart.tex (the Apart submission template layout) from paper/main.tex: same content, template heading order and styles. Run from the repo root, then compile with xelatex."""
import re
src = open("paper/main.tex").read()

def between(a, b):
    i = src.index(a); j = src.index(b, i + len(a))
    return src[i + len(a):j]

body_start = src.index(r"\begin{document}")
pre = src[:body_start]
# keep macro/colour/box definitions, drop font, page and heading set-up
keep = []
for line in pre.splitlines():
    if line.startswith(("\\documentclass", "\\usepackage[T1]", "\\usepackage[utf8]", "\\usepackage{newtx", "\\usepackage[letterpaper", "\\pagestyle", "\\renewcommand{\\headrulewidth", "\\titleformat", "\\titlespacing")):
        continue
    keep.append(line)
pre_keep = "\n".join(keep)

title_fn = re.search(r"Rig Procurement Auctions(\\footnote\{.*?\})\}\n", src).group(1)
abstract = between("\\begin{quote}\n", "\\end{quote}")
intro = between("\\section{Introduction}\n", "\\section{Setting up the Auction}")
setup = between("\\section{Setting up the Auction}\n", "\\section{Evaluation Framework}")
evalf = between("\\section{Evaluation Framework}\n", "\\section{Experiments and Analysis}")
results = between("\\section{Experiments and Analysis}\n", "\\section{Discussion and Limitations}")
disc = between("\\section{Discussion and Limitations}\n", "\\section{Conclusion}")
concl = between("\\section{Conclusion}\n", "\\section*{Author Contributions}")
contrib = between("\\section*{Author Contributions}\n", "\\begin{thebibliography}")
bib = "\\begin{thebibliography}" + between("\\begin{thebibliography}", "\\end{thebibliography}") + "\\end{thebibliography}\n"
related = between("\\section{Related Work}\n", "\\section{Metric Definitions and Tests}")
app_rest = between("\\section{Metric Definitions and Tests}", "\\section{Code and Data}")
code = between("\\section{Code and Data}\n", "\\section{LLM Usage Statement}")
llm = between("\\section{LLM Usage Statement}\n", "\\end{document}")

lim_i = disc.index("\\para{Limitations.} "); fut_i = disc.index("\\para{Future work.} ")
disc_main = disc[:lim_i]
limitations = disc[lim_i + len("\\para{Limitations.} "):fut_i]
future = disc[fut_i + len("\\para{Future work.} "):]

# results subsections and methods parts become level-3 headings
results = results.replace("\\subsection{", "\\subsection{")
app = "\\subsection{Metric Definitions and Tests}" + app_rest
app = app.replace("\\section{", "\\subsection{")

preamble = r"""\documentclass[12pt]{article}
\usepackage[letterpaper,margin=1in]{geometry}
\usepackage{graphicx,booktabs,amsmath,xcolor,enumitem,caption,microtype,tikz,colortbl,multirow,float}
\usepackage{newtxmath}
\usepackage[no-math]{fontspec}
\setmainfont{Times New Roman}
\usepackage{setspace}\setstretch{1.15}
\usepackage{titlesec,needspace}
\usepackage[section,above]{placeins}
\usepackage{flafter}
\definecolor{headtwo}{HTML}{434343}\definecolor{headthree}{HTML}{666666}
\titleformat{\section}{\needspace{6\baselineskip}\fontsize{14}{17}\selectfont\bfseries\color{headtwo}}{\thesection.}{0.35em}{}
\titleformat{\subsection}{\fontsize{13}{16}\selectfont\bfseries\color{headthree}}{\thesubsection}{0.5em}{}
\titlespacing*{\section}{0pt}{10pt}{2pt}
\titlespacing*{\subsection}{0pt}{10pt}{2pt}
\pagestyle{plain}
"""
doc = preamble + pre_keep.replace("\\documentclass[10pt]{article}", "") + r"""
\begin{document}

\noindent\rule{\textwidth}{1pt}
\begin{center}
{\fontsize{20}{25}\selectfont\bfseries TAKING THE CHANNEL AWAY: OPEN MESSAGES, NOT NOTES, LET LLM BIDDERS RIG PROCUREMENT AUCTIONS""" + title_fn + r"""}
\end{center}
\noindent\rule{\textwidth}{1pt}

\begin{center}
Linus C.\\ {[Affiliation]}\\ \texttt{[email]}

\vspace{0.8em}
\textbf{With}\\ Apart Research
\end{center}

\begin{center}{\fontsize{14}{17}\selectfont\bfseries Abstract}\end{center}
\begin{list}{}{\setlength{\leftmargin}{0.375in}\setlength{\rightmargin}{0.03in}}\item[]
""" + abstract.strip() + r"""
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
open("paper/main_apart.tex", "w").write(doc)
print("written", len(doc))
