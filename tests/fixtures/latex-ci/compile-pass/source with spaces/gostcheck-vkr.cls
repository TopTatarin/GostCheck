\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{gostcheck-vkr}[2026/07/25 Synthetic CI fixture class]
\LoadClass{article}
\RequirePackage{fontspec}
\IfFontExistsTF{Times New Roman}
  {\setmainfont{Times New Roman}}
  {\setmainfont{TeX Gyre Termes}}
\RequirePackage[backend=biber,style=gost-numeric,sorting=none]{biblatex}
\PackageWarningNoLine{gostcheck-vkr}{Synthetic non-blocking warning}
