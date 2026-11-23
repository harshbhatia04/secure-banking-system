# Live local transfer model

The web route runs [local review](../local_review.py) after a transfer commits. Version 2 uses gradient-boosted decision trees trained on payment history. It considers up to 20 prior outgoing transfers, including their amounts and payments to the same recipient. It also considers earlier activity that UTC day and the median amount of up to 256 recent transfers across all accounts. The influence of this last amount is capped based on the sender's own history. The amount features use ratios, so converting rupees to paise leaves those inputs the same.

The model needs three prior transfers to score a payment. The Risk Desk shows flagged payments for manual review. SQLite records the model version, threshold, decision and transaction context at payment time. Historical receipts keep their original assessments.

To reproduce, install `requirements.txt`, place the credited BankSim CSV in `data/external/banksim.csv`, and run `python train_transfer_profile.py`. The trainer fits on days before 120 and selects the model and threshold on days 120 through 146. Its selection checks include a routine payment and a large deviation from a sender's baseline. It reports results on days 147 onward, the same later-day benchmark used earlier in the project. It verifies that the exported model produces the same scores as scikit-learn across the full scored test set. The website loads the exported JSON and evaluates the trees with standard Python.

| Model | Scored test payments | Precision | Recall | Average precision |
| --- | ---: | ---: | ---: | ---: |
| Original offline logistic regression | 122,278 | 83.6% | 51.5% | 0.693 |
| Previous live model, version 1 | 122,276 | 47.5% | 37.0% | 0.407 |
| Live model, version 2 | 122,276 | 75.6% | 60.0% | 0.720 |

Version 2 flagged 792 labelled frauds and 255 legitimate payments. It missed 527 of the scored frauds, while two payments lacked enough history for a score, including one labelled fraud. Precision measures the share of alerts that were labelled fraud. Recall measures the share of scored fraud cases the model caught. These results apply to simulated BankSim payments. Accuracy on real INR transfers still requires independent labelled data.

## Earlier offline model

For comparison, the original classifier below used the numerical amount directly. Its BankSim performance was stronger, but substituting rupees for the dataset's amount unit made ordinary demo payments appear extreme.

The separate local prototype is a logistic-regression model trained on [BankSim: Synthetic data from a financial payment system](https://www.kaggle.com/ntnu-testimon/banksim1), created by TESTIMON/NTNU from simulated bank-payment activity. The dataset is published under [CC BY-NC-SA 4.0](https://github.com/prinz-nussknacker/banksim1/blob/master/README.md). This university project uses it for a noncommercial demonstration. The CSV was downloaded from a [public GitHub mirror](https://github.com/niravdedhiya/Fraud-Detection-BankSim/tree/main/data); the original Kaggle page is the dataset source. BankSim has 594,643 labelled transactions, including 7,200 fraud cases. The live website does not use this model to score transfers.

`python train_fraud_model.py --download` downloads the CSV to `data/external/banksim.csv`, derives three features from each event, trains on the earlier days, evaluates on the later days and writes `data/banksim_model.json`. The raw CSV stays outside Git. The model parameters and metrics travel with the project for inspection. Re-run the trainer to change the prototype model; this does not change live fraud reviews.

| Input to model | BankSim training field | Live banking field |
| --- | --- | --- |
| Amount | `amount`, log transformed | Transfer amount in rupees, log transformed |
| Earlier activity | Earlier payments by that customer in the same simulated day | Earlier transfers by this source account in the last 24 hours |
| New recipient | Whether customer has paid that merchant before | Whether source account has transferred to this destination before |

The last two inputs are *conceptually* similar, not identical. BankSim's amount unit is also not Indian rupees. The scores are therefore **not calibrated for this app's live transactions**; an alert asks for human review and does not reject the committed transfer.

The fixed later-day test has 122,278 rows, including 1,320 fraud cases. Average precision is 0.693. At the stored 50% alert threshold, precision is 83.6% and recall is 51.5% on BankSim test rows. These are BankSim metrics, not a claim of performance on actual customers or this app's live data. The trainer records the source SHA-256 and test counts in `data/banksim_model.json`.

The login path is separate. The app records unsuccessful sign-ins, throttles after five within five minutes, and creates a `login_failures` **rule** alert. BankSim has no login examples. We also inspected the [RBA risk-based authentication dataset](https://github.com/das-group/rba-dataset), which labels account takeovers, but its small public demonstration fixture did not support a reliable detector from the limited login features this local site records. No login alert is claimed to come from the BankSim model.

## Optional interim Groq API review

When `GROQ_API_KEY` is set, new transfers use an external Groq-hosted language model for an interim manual-review signal. The default model is `openai/gpt-oss-20b`; `GROQ_MODEL` can override it. The key stays in the environment and is never committed. The app sends only the INR amount, number of earlier outgoing transfers in the last 24 hours, and whether the destination is new. The model returns a structured `low`/`medium`/`high` concern level, a review flag, and a short reason. Flagged transfers create a `groq_review` alert in Risk Desk. This is an LLM-assisted review, not a trained fraud probability or a confirmed fraud decision. It has not been evaluated on a labelled banking holdout.

Local review and the fixed rules run regardless of Groq availability. A configured API failure is shown to the user after the transfer commits.

To enable the interim review, create a new Groq key, set it as `GROQ_API_KEY` in the server's environment, and restart the web server. Do not paste a key into chat, code, screenshots, or Git. The Groq request uses its [Chat Completions API](https://console.groq.com/docs/api-reference) and [strict structured output](https://console.groq.com/docs/structured-outputs).
