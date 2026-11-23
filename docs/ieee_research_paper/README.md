# IEEE banking research manuscript

Open `main.tex` in Overleaf and choose pdfLaTeX. The file uses the standard
`IEEEtran` conference class. Figures are drawn in TikZ/PGFPlots and references
are embedded, so no image upload or separate bibliography file is required.

Template basis: https://www.overleaf.com/latex/templates/ieee-conference-template/grfzhhncsfqn

This is a manuscript for mentor review, not a published or accepted IEEE paper.
The formatting follows the generic conference template; a specific venue may
have different page limits, anonymous-review requirements or paper-size rules.

## Evidence

`evidence/evaluation_results.json` contains the 24 recorded workloads from
2 November 2026, summary statistics, environment information and core source
hashes. Its test-suite entry records the observed result of 45 passing tests.
`evidence/model_evaluation.json` contains re-scoring results for the saved
BankSim classifier on its existing later-day holdout. It is not a new training
run or an independent validation set.

The corresponding scripts remain in the banking source workspace:

    python -m unittest discover -s tests -v
    python docs/research/evaluate.py
    python docs/research/evaluate_model.py

Do not run those commands inside an Overleaf project. They require the banking
source checkout; the model check also requires its locally stored BankSim CSV.

The raw dataset and API credentials are not included in this package.
No plagiarism or AI detector was run on this manuscript, and no detector score
is claimed. Review the text and evidence with the named authors before submission.
