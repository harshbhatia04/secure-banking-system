# Public-data fraud model

The website's **AI Risk** alert uses a local logistic-regression model trained on [BankSim: Synthetic data from a financial payment system](https://www.kaggle.com/ntnu-testimon/banksim1), created by TESTIMON/NTNU from simulated bank-payment activity. The dataset is published under [CC BY-NC-SA 4.0](https://github.com/prinz-nussknacker/banksim1/blob/master/README.md). This university project uses it for a noncommercial demonstration. The CSV was downloaded from a [public GitHub mirror](https://github.com/niravdedhiya/Fraud-Detection-BankSim/tree/main/data); the original Kaggle page is the dataset source. BankSim has 594,643 labelled transactions, including 7,200 fraud cases.

`python train_fraud_model.py --download` downloads the CSV to `data/external/banksim.csv`, derives three features from each event, trains on the earlier days, evaluates on the later days and writes `data/banksim_model.json`. The raw CSV stays outside Git. The model parameters and metrics travel with the project, so running the local website needs no network access or API key. Re-run the trainer and restart the site to change the model.

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

If Groq is not configured, the local BankSim model above is used. If a configured API call fails or returns an invalid response, the committed transfer remains intact, a message tells the user that Groq was unavailable, and the local model checks it instead. The deterministic high-value, rapid-activity, failure and login rules remain separate.

To enable the interim review, create a new Groq key, set it as `GROQ_API_KEY` in the server's environment, and restart the web server. Do not paste a key into chat, code, screenshots, or Git. The Groq request uses its [Chat Completions API](https://console.groq.com/docs/api-reference) and [strict structured output](https://console.groq.com/docs/structured-outputs).
