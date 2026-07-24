\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{gostcheck-vkr}[2025/01/01 GostCheck fixture class]
\LoadClass{article}
\RequirePackage{fontspec}
\setmainfont{Times New Roman}
\RequirePackage{titlesec}
\RequirePackage{setspace}
\onehalfspacing
\setlength{\parindent}{12.5mm}
\RequirePackage[left=30mm,right=10mm,top=20mm,bottom=20mm]{geometry}
\RequirePackage{caption}
\captionsetup[figure]{labelsep=endash,position=below,justification=centering,font={stretch=1},hyphenpenalty=10000}
\captionsetup[table]{position=top,singlelinecheck=off,justification=raggedright}
\newcommand{\risref}[1]{рисунке~\ref{#1}}
\newcommand{\vkrlongtable}[1]{\begin{longtable}{#1}\endfirsthead}
\RequirePackage{chngcntr}
\counterwithin{figure}{section}
\counterwithin{table}{section}
\RequirePackage{amsmath}
\RequirePackage{longtable}
\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex-gost}
% tampered
