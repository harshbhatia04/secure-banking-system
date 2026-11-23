"""Build the research manuscript from verified local experiment artifacts."""
from pathlib import Path
import json
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon, Circle

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/pdf/banking_system_research_paper.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
R = json.loads(Path(__file__).with_name('evaluation_results.json').read_text())
M = json.loads(Path(__file__).with_name('model_evaluation.json').read_text())
W = A4[0] - 100
BLUE = colors.HexColor('#203D58')
MUTED = colors.HexColor('#56636E')
PALE = colors.HexColor('#F1F5F7')
styles = {
 'title': ParagraphStyle('title', fontName='Times-Bold', fontSize=21, leading=24, alignment=TA_CENTER, spaceAfter=12),
 'authors': ParagraphStyle('authors', fontName='Times-Roman', fontSize=11, leading=15, alignment=TA_CENTER, spaceAfter=5),
 'meta': ParagraphStyle('meta', fontName='Helvetica', fontSize=8.5, leading=12, alignment=TA_CENTER, textColor=MUTED, spaceAfter=13),
 'h1': ParagraphStyle('h1', fontName='Times-Bold', fontSize=13, leading=16, spaceBefore=10, spaceAfter=6, keepWithNext=True),
 'h2': ParagraphStyle('h2', fontName='Times-Bold', fontSize=11, leading=14, spaceBefore=8, spaceAfter=4, keepWithNext=True),
 'body': ParagraphStyle('body', fontName='Times-Roman', fontSize=10.5, leading=14, alignment=TA_JUSTIFY, spaceAfter=7),
 'small': ParagraphStyle('small', fontName='Times-Roman', fontSize=9, leading=11.8, spaceAfter=5),
 'caption': ParagraphStyle('caption', fontName='Times-Italic', fontSize=9, leading=12, spaceBefore=5, spaceAfter=9),
 'cell': ParagraphStyle('cell', fontName='Times-Roman', fontSize=9.2, leading=11.5),
 'th': ParagraphStyle('th', fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.white),
 'equation': ParagraphStyle('equation', fontName='Times-Italic', fontSize=11, leading=16, alignment=TA_CENTER, spaceBefore=4, spaceAfter=9),
 'ref': ParagraphStyle('ref', fontName='Times-Roman', fontSize=9, leading=12, leftIndent=17, firstLineIndent=-17, spaceAfter=8),
}
story, markdown = [], []

def p(text, kind='body'):
    story.append(Paragraph(text, styles[kind]))
    plain = re.sub('<[^>]+>', '', text)
    prefix = {'title': '# ', 'h1': '## ', 'h2': '### '}.get(kind, '')
    markdown.append(prefix + plain + '\n')

def page():
    story.append(PageBreak())
    markdown.append('\n---\n')

def table(headers, rows, widths):
    data = [[Paragraph(escape(str(x)), styles['th']) for x in headers]]
    data += [[Paragraph(escape(str(x)), styles['cell']) for x in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), BLUE), ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, PALE]),
        ('LINEBELOW',(0,-1),(-1,-1),0.6,BLUE),
        ('LINEBELOW',(0,0),(-1,0),0.6,BLUE),
    ]))
    story.append(t)
    story.append(Spacer(1,6))
    markdown.append('| ' + ' | '.join(headers) + ' |\n| ' + ' | '.join(['---']*len(headers)) + ' |')
    markdown.extend('| ' + ' | '.join(str(x) for x in row) + ' |' for row in rows)
    markdown.append('')

def arrow(d, x1, y1, x2, y2, dashed=False):
    d.add(Line(x1,y1,x2,y2,strokeColor=BLUE,strokeWidth=1,strokeDashArray=[3,2] if dashed else None))
    if x1 == x2:
        direction = 1 if y2>y1 else -1
        d.add(Polygon([x2,y2,x2-3,y2-6*direction,x2+3,y2-6*direction],fillColor=BLUE,strokeColor=BLUE))
    else:
        direction = 1 if x2>x1 else -1
        d.add(Polygon([x2,y2,x2-6*direction,y2-3,x2-6*direction,y2+3],fillColor=BLUE,strokeColor=BLUE))

def architecture():
    d = Drawing(W,250)
    def box(x,y,w,h,lines,fill=PALE):
        d.add(Rect(x,y,w,h,rx=4,ry=4,fillColor=fill,strokeColor=BLUE,strokeWidth=.8))
        for j,line in enumerate(lines):
            d.add(String(x+w/2,y+h/2+((len(lines)-1)/2-j)*12,line,
                         textAnchor='middle',fontName='Helvetica-Bold' if j==0 else 'Helvetica',fontSize=8.5,fillColor=BLUE))
    box(8,204,224,40,['Browser / Flask','login, ownership, CSRF, forms'])
    box(263,204,224,40,['CLI / threaded simulator','controlled requests and temporary lab'])
    arrow(d,120,204,120,182); arrow(d,375,204,375,182)
    box(8,135,479,47,['Transaction service','validate -> sorted account mutexes -> BEGIN IMMEDIATE',
                       'read/check -> debit + credit + ledger row -> commit'])
    arrow(d,247,135,247,117)
    box(8,69,479,48,['SQLite storage: one writer','users, accounts, committed transactions, failed attempts',
                      'fraud alerts, login attempts, transaction events'])
    arrow(d,118,69,118,49)
    box(8,3,224,46,['After-commit review / traces','deterministic rules; optional Groq','separate writes; review does not undo payment'])
    box(263,3,224,46,['Offline experiment (separate)','BankSim -> features -> saved logistic model','not used for live website decisions'])
    return d

def timing_plot():
    d = Drawing(W,180)
    x0,y0,xstep,yscale=42,32,120,21
    for value in range(0,7):
        y=y0+value*yscale
        d.add(Line(x0,y,W-18,y,strokeColor=colors.HexColor('#DDE3E7'),strokeWidth=.5))
        d.add(String(x0-8,y-3,str(value),fontName='Helvetica',fontSize=8,textAnchor='end'))
    palette={'transfer':BLUE,'mixed':colors.HexColor('#8B5837')}
    for mode in ('transfer','mixed'):
        pts=[]
        for i, workers in enumerate((1,5,10,20)):
            row=next(x for x in R['summary'] if x['mode']==mode and x['workers']==workers)
            x=x0+20+i*xstep + (-4 if mode=='transfer' else 4)
            y=y0+row['mean_seconds']*yscale
            err=row['sample_sd_seconds']*yscale
            color=palette[mode]
            d.add(Line(x,y-err,x,y+err,strokeColor=color,strokeWidth=1))
            d.add(Line(x-4,y-err,x+4,y-err,strokeColor=color))
            d.add(Line(x-4,y+err,x+4,y+err,strokeColor=color))
            d.add(Circle(x,y,3,fillColor=color,strokeColor=color))
            if pts:
                d.add(Line(*pts[-1],x,y,strokeColor=color,strokeWidth=1))
            pts.append((x,y))
    for i,workers in enumerate((1,5,10,20)):
        d.add(String(x0+20+i*xstep,18,str(workers),textAnchor='middle',fontName='Helvetica',fontSize=8.5))
    d.add(String(5,170,'Seconds',fontName='Helvetica',fontSize=8))
    d.add(String(W/2,3,'Worker count (equally spaced categories)',textAnchor='middle',fontName='Helvetica',fontSize=8))
    for x,mode in [(290,'transfer'),(380,'mixed')]:
        d.add(Line(x,170,x+17,170,strokeColor=palette[mode],strokeWidth=2))
        d.add(String(x+22,167,mode.title(),fontName='Helvetica',fontSize=8))
    return d

p('Atomic Transfers and Observable Concurrency<br/>in a SQLite Banking Prototype', 'title')
p('Harsh Bhatia &nbsp; | &nbsp; Tanisha Kapoor &nbsp; | &nbsp; Prakhar Garg', 'authors')
p('Graphic Era (Deemed to be University), Dehradun, India<br/>Project Alpha / OSDBMS-V-2026-T234 &nbsp; | &nbsp; Research manuscript, 2 November 2026', 'meta')
p('Abstract', 'h1')
p('A bank transfer can fail even when its debit and credit statements are individually valid: an interruption between them can leave an incomplete payment, while concurrent requests can act on stale balances. This paper presents a small Python and SQLite banking prototype that makes these problems observable. The implementation combines ordered account mutexes, explicit database transactions, persistent request keys and separate records for failed attempts. A Flask interface exposes customer operations, administrative review and a concurrency laboratory. Evaluation on a local Windows machine included 45 automated tests and 24 repeated workloads containing 2,400 operations. All tests passed; every workload preserved its accounting invariant and completed without rejected operations. Transfer-only timings did not show a consistent improvement as the worker count increased. A separate re-evaluation of a saved BankSim classifier produced average precision of 0.6926 and recall of 51.52% at a 0.5 threshold. The work provides a reproducible teaching case connecting operating-system synchronization, database transactions and cautious interpretation of fraud alerts. It does not establish production readiness or detection performance on real customer payments.')
p('<b>Keywords:</b> atomic transactions; SQLite; thread synchronization; idempotency; banking simulation; fraud review.', 'small')
p('1. Introduction', 'h1')
p('Consider two withdrawals that both read an account balance before either updates it. Without a protected check-and-update sequence, each request may appear affordable even though their combined amount is not. Transfers add a second failure point because money must leave one account and reach another as one unit. Our project uses these concrete cases to connect OS concepts such as mutual exclusion and circular wait with DBMS concepts such as constraints, commit and rollback.')
p('The study asks three questions: <b>RQ1</b>, do the tested concurrent and failure paths preserve the intended accounting rules? <b>RQ2</b>, how does completion time change between one and twenty worker threads? <b>RQ3</b>, what evidence supports the system\'s fraud-review features? Its contribution is the implementation, observable demonstrations and reproducible evaluation of established techniques, rather than a new locking algorithm.')
p('2. Background and related work', 'h1')
p('Berenson et al. [1] explain why isolation must be understood through the anomalies a schedule permits. This motivates explicit checks of balances, rollback and duplicate requests in our evaluation. SQLite documents serialized writes and the writer reservation obtained by BEGIN IMMEDIATE [2]; this is the database mechanism used here. Python provides the mutex and timeout primitives for the process-local account layer [3]. BankSim [4] supplies a separate synthetic-data setting for classification. Saito and Rehmsmeier [5] motivate examining precision and recall when the positive class is rare. These sources support the design choices; our measurements concern only the local implementation described below.')

page()
p('3. System architecture and transaction protocol', 'h1')
story.append(architecture())
p('Figure 1. Implemented components and execution boundaries. Solid arrows show the main request/storage path. The BankSim experiment has no connection to the current live transfer path.', 'caption')
p('3.1 Data representation and access boundaries', 'h2')
p('Balances and amounts use integer paise. Users own accounts; successful transactions have unique request keys. Schema checks reject negative balances and invalid operation/source/destination combinations. Failed attempts occupy a separate table so that their records survive payment rollback. Alerts, login attempts and execution events are also separate from the ledger.')
p('Flask checks login state, role, account ownership and form tokens. The trusted CLI and simulator call the service directly. Each operation opens its own SQLite connection. The local database uses WAL mode, enabled foreign keys and synchronous FULL.')
p('3.2 Transfer sequence', 'h2')
p('<b>(1)</b> Validate input. <b>(2)</b> Acquire account mutexes in ascending account-ID order with a bounded wait. <b>(3)</b> Open a connection and issue BEGIN IMMEDIATE. <b>(4)</b> Return the earlier result for an identical committed request key; reject conflicting reuse. <b>(5)</b> Read current account state, check status and funds, debit, credit and insert the ledger row. <b>(6)</b> Commit, close and release locks. An error within the database transaction triggers rollback; eligible failures are audited afterward in a separate transaction.')
p('Manager objects in one process share mutexes by resolved database path. Ordered acquisition prevents circular wait among account locks: a thread cannot hold a higher-ID lock while awaiting a lower-ID lock. It does not guarantee fairness or bound the entire operation to the lock timeout. Independent processes rely on SQLite because they do not share Python mutexes.')
p('3.3 Observation and review', 'h2')
p('Web traces record lock and database events, then persist after payment commit. Rule checks and optional Groq review also follow commit; alerts do not cancel payments. These records are not atomic with the payment. The laboratory uses temporary databases and dummy-memory race/deadlock examples.')

page()
p('4. Evaluation method', 'h1')
p('4.1 Accounting properties', 'h2')
p('Let B(t) be the sum of all account balances after the observed workload, D the sum of successful deposits and W the sum of successful withdrawals. Internal transfers should preserve the total, while a mixed workload should satisfy:')
p('B(final) = B(initial) + D - W, with every account balance at least zero.', 'equation')
p('The simulator checks this equality, nonnegative balances, completed worker threads and whether every requested operation has a success or rejection outcome. Individual tests additionally inspect the ledger and failure records. For an injected error after the source debit, the expected outcome is unchanged balances and no committed payment row. For repeated identical request keys, exactly one payment should move money. These are checks of specific executions, not an exhaustive proof over all schedules.')
p('4.2 Test scenarios', 'h2')
table(['Scenario', 'Observed assertion in the passing suite'],[
 ('Concurrent deposits','100 deposits of INR 100 produce INR 20,000 from INR 10,000; the ledger contains 100 rows.'),
 ('Competing withdrawals','20 requests for INR 1,000 against INR 10,000 yield 10 successes and a zero closing balance.'),
 ('Rollback and cleanup','Failure after debit restores both balances; no success row remains, and another thread can subsequently transfer.'),
 ('Request replay','20 concurrent uses of one request key yield one new payment; conflicting reuse is rejected.'),
 ('Opposing transfers','Two threads each perform 25 transfers in opposite directions and restore the starting balances.'),
 ('Separate lock registries','40 concurrent deposits using independent mutex registries preserve the expected total through database serialization.'),
 ('Web and review boundaries','Tests cover ownership, CSRF, roles, alert rules, trace receipts and mocked external-review failures.'),
 ],[119,W-119])
p('Table 1. Selected assertions from 45 passing tests. The independent-registry scenario uses threads in one process; it is not a multiprocess deployment test.', 'caption')
p('4.3 Workload and timing protocol', 'h2')
p('Each benchmark started with a new temporary database and three active accounts containing INR 10,000 each. There were 100 queued requests per run. Transfer-only workloads selected two distinct accounts and an integer amount from INR 1 to INR 100. Mixed workloads additionally selected deposit, withdrawal or transfer with equal probability. We tested 1, 5, 10 and 20 workers in both modes, with three repetitions per configuration. Workload seed 42 fixed the request sequence; configuration order was shuffled using seed 2026. Thread scheduling remained uncontrolled.')
p(f'The environment was Python {R["python"]}, SQLite {R["sqlite"]}, and {R["platform"]}. The processor identifier was {escape(R["processor"])}. The timer included worker creation, barrier synchronization and completion, but excluded schema creation, seeding and workload construction. Runs used the service directly without web tracing or external API calls. No background-load or power-state controls were applied. Mean time, sample standard deviation and mean per-run throughput are reported descriptively; three repetitions are too few for a strong performance claim.')

page()
p('5. Transaction and concurrency results', 'h1')
p('The automated suite completed 45 tests in 121.108 seconds with no failures. All 24 benchmark runs passed the accounting, nonnegative-balance and operation-completion checks. Across the runs, 2,400 requests succeeded and none were rejected; no unexpected errors or failure-audit warnings were reported. These workload results concern small, sufficiently funded operations. The separate withdrawal test in Table 1 exercises rejection under insufficient funds.')
rows=[]
for row in R['summary']:
    rows.append((row['mode'].title(),str(row['workers']),f'{row["mean_seconds"]:.3f}',f'{row["sample_sd_seconds"]:.3f}',f'{row["mean_ops_per_second"]:.2f}'))
table(['Workload','Workers','Mean time (s)','Sample SD (s)','Mean ops/s'],rows,[102,60,112,112,W-386])
p('Table 2. Three runs per configuration; 100 operations per run. Throughput is the mean of the three individual run rates, so it need not equal 100 divided by the mean time.', 'caption')
story.append(timing_plot())
p('Figure 2. Completion time for 100 requests. Error bars show one sample standard deviation across three repetitions, not confidence intervals.', 'caption')
p('For transfer-only workloads, mean completion time stayed between 3.67 and 4.00 seconds across worker counts. The small differences and overlapping variability provide no clear evidence of a throughput gain from more threads. Mixed workloads were faster at twenty workers than at one in this sample, but they did not improve monotonically at every intermediate count. The experiment does not isolate whether scheduling, disk activity, connection overhead or another factor caused these differences.')
p('SQLite accepts one writer at a time [2], and the workload touches only three accounts, creating contention at the account layer as well. More submitted work therefore need not mean more simultaneous database updates. Ordered mutexes make the application\'s coordination visible; their performance benefit was not measured because the benchmark contains no comparison with that layer removed. The useful result here is preserved accounting under the tested schedules, rather than a scalability claim.')

page()
p('6. Fraud review and the offline BankSim experiment', 'h1')
p('6.1 Current website behavior', 'h2')
p('The live website records understandable rule alerts, including transfers of at least INR 5,000 and five transfers from the same source within sixty seconds. Additional checks cover repeated failed outgoing operations, repeated failed logins and unauthorized account access. These thresholds were chosen for the demonstration and have not been calibrated against real customer behavior. Rule activation tests establish that selected conditions trigger alerts; they do not measure fraud-detection accuracy.')
p('If configured, an external Groq review receives transaction context and returns a concern category and explanation. Tests replace the remote service with controlled responses, including an error response. No live-provider accuracy, latency or availability experiment was performed. The current website does not fall back to the saved BankSim classifier when that service fails. Rule checks remain the local review mechanism, and the already committed payment is not reversed by a review failure.')
p('6.2 Dataset, features and verification protocol', 'h2')
p('BankSim was developed to generate synthetic payment data for fraud research [4]. The local CSV contains 594,643 rows. The existing training code uses three inputs: log(1 + amount), the number of earlier payments for that customer on the same day capped at twenty, and whether the customer-merchant pair has appeared previously. Features are formed before updating the historical counters. Standardization is fitted on training rows, followed by logistic regression with a maximum of 1,000 iterations and random state 42.')
p('The recorded temporal split contains 472,365 training rows with 5,880 fraud labels and 122,278 test rows with 1,320 fraud labels; the later period begins at step 147. For this paper, the saved coefficients were re-scored on that test period without refitting. A fresh scan found no decreasing day steps in file order, and the CSV SHA-256 matched the training artifact. This verifies the recorded calculation on the same holdout, rather than supplying a new independent test set. Within-day sequence follows CSV order; finer event chronology is unavailable in this evaluation.')
table(['Holdout quantity','Verified value'],[
 ('Average precision',f'{M["average_precision"]:.4f}'),
 ('Precision at score >= 0.5',f'{M["precision"]*100:.2f}%'),
 ('Recall at score >= 0.5',f'{M["recall"]*100:.2f}%'),
 ('True positives / false positives',f'{M["true_positive"]:,} / {M["false_positive"]:,}'),
 ('False negatives / true negatives',f'{M["false_negative"]:,} / {M["true_negative"]:,}'),
 ],[W*.62,W*.38])
p('Table 3. Re-evaluation of the saved model on its original later-day BankSim holdout. These are offline scores, not website or real-bank accuracy.', 'caption')
p('Only about 1.08% of test rows carry a fraud label, making accuracy alone a poor summary: predicting every row as legitimate would already be about 98.92% accurate. Precision-recall analysis is more revealing in this setting [5]. Average precision aggregates precision over recall increments [6]. At the chosen threshold, 680 of 1,320 labelled fraud cases were detected and 640 were missed. The test therefore supports a limited screening experiment, not a claim that most fraud will be prevented. No new threshold tuning or probability calibration was performed.')

page()
p('7. Discussion and limitations', 'h1')
p('7.1 What the evidence supports', 'h2')
p('For RQ1, the selected tests and small concurrent workloads show the expected accounting behavior: the implementation does not retain the injected partial debit, spend beyond the tested available funds, or move money again for an identical committed request key. The database transaction is the boundary that groups balance changes with the successful ledger row. The account mutexes give the application an explicit coordination policy and a useful teaching trace. Their ordering argument applies only to that set of locks, not to every resource a future extension might acquire.')
p('For RQ2, the transfer-only results are consistent with a system whose update path remains serialized despite additional worker threads. They do not identify a best worker count. A controlled follow-up should vary the number of accounts and operations, include several workload seeds, report operation-level latency percentiles and compare explicit account locking with database-only serialization. Longer runs and more repetitions would help separate startup and filesystem effects from sustained throughput.')
p('For RQ3, the project has three different types of evidence. Rule tests check implementation behavior. Mocked external-review tests check integration behavior. The BankSim holdout measures one saved model on a synthetic distribution. None of these is a substitute for evaluating the actual website on representative labelled payments. In particular, the model\'s dataset-day count differs from a rolling twenty-four-hour website count, and its amount distribution has not been validated for the INR demonstration. This is why the offline result is presented separately.')
p('7.2 Threats to validity', 'h2')
p('<b>Coverage and schedule limits.</b> A finite passing suite cannot rule out every interleaving. The independent-registry test does not launch separate OS processes. The dummy lost-update and circular-wait demonstrations intentionally force a failure pattern; they are teaching examples, not measurements of its frequency in a deployed service. Timeouts bound selected waits but do not establish fairness or starvation freedom.')
p('<b>Persistence and deployment limits.</b> Rollback testing injects a Python-level failure, not a power loss or storage-device fault. WAL and synchronous FULL are configured, but crash recovery, backup restoration, replication and failover were not tested. Failure audits, traces and alerts are separate writes. A committed payment may therefore exist without all of its supporting review records if a subsequent write fails. Reliable delivery of those records would need additional design and evaluation.')
p('<b>Measurement limits.</b> All timings come from one Windows machine, three accounts and short local workloads. No web-network latency, large account population, long-lived workload, controlled disk state or production traffic was included. The same request seed was repeated to hold request mix constant; the experiment does not measure sensitivity to other mixes. No statistical significance or comparison with another database is claimed.')
p('<b>Detection limits.</b> The BankSim calculation reuses an existing holdout and saved coefficients. Its labels come from simulation, and its features retain the input file\'s within-day ordering. There is no real-customer validation, cost-sensitive threshold selection, drift study or calibrated interpretation of scores. External concern labels are also not probabilities of fraud. All alerts require contextual review.')
p('8. Conclusion', 'h1')
p('The prototype provides a concrete setting in which students can follow a payment from a concurrent request through locking, transactional updates and review records. Forty-five tests and twenty-four benchmark runs supported the intended accounting behavior under the evaluated conditions. Timing variation and SQLite\'s single-writer design limit performance conclusions. The separate BankSim result further shows why a plausible fraud score must be accompanied by recall, data provenance and deployment limits. Future work should broaden failure and multiprocess testing, improve review-record reliability and evaluate detection on an appropriate independent dataset.')

page()
p('Reproducibility and project responsibilities', 'h1')
p('The accompanying source workspace contains the following experiment scripts and evidence. The benchmark operates on temporary databases and leaves the demonstration banking database unchanged. Source hashes in the result files identify the evaluated implementation. The model check uses the existing local CSV; its original data location and download mirror are recorded in data/banksim_model.json.', 'small')
table(['Artifact / command from project root','Purpose'],[
 ('python -m unittest discover -s tests -v','Run the banking, web, model-artifact and mocked review tests.'),
 ('python docs/research/evaluate.py','Repeat the 24 threaded workloads; writes evaluation_results.json in the same directory.'),
 ('python docs/research/evaluate_model.py','Re-score the saved classifier; writes model_evaluation.json with the source hash and confusion counts.'),
 ('python docs/research/build_paper.py','Build this PDF and the editable Markdown manuscript using ReportLab.'),
 ],[W*.54,W*.46])
p('Use the project Python environment for the test suite and benchmark; rebuilding the PDF additionally requires ReportLab. The model-verification script uses the Python standard library and requires data/external/banksim.csv. Re-running experiments will change timings. The run reported here was performed on 2 November 2026.', 'small')
p('<b>Project responsibilities:</b> Harsh Bhatia - atomic operations, thread coordination, race/deadlock demonstrations and fraud-review work. Tanisha Kapoor - database schema, storage, queries and project documentation. Prakhar Garg - web interface, integration and testing, with supporting work on database-backed displays and thread/lock-event visualization.', 'small')
p('References', 'h1')
references = [
 ('1', 'H. Berenson, P. Bernstein, J. Gray, J. Melton, E. O\'Neil and P. O\'Neil. "A Critique of ANSI SQL Isolation Levels." Proceedings of ACM SIGMOD, pp. 1-10, 1995. Technical report MSR-TR-95-51.', 'https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf', 'Microsoft Research full text'),
 ('2', 'SQLite. "Isolation in SQLite." Official documentation. Accessed 2 November 2026.', 'https://www.sqlite.org/isolation.html', 'sqlite.org/isolation.html'),
 ('3', 'Python Software Foundation. "threading - Thread-based parallelism." Python 3.12 documentation. Accessed 2 November 2026.', 'https://docs.python.org/3.12/library/threading.html', 'Python threading documentation'),
 ('4', 'E. A. Lopez-Rojas and S. Axelsson. "BankSim: A Bank Payments Simulator for Fraud Detection Research." Proceedings of the 26th European Modeling and Simulation Symposium, pp. 144-152, 2014.', 'https://www.msc-les.org/proceedings/emss/2014/EMSS2014_144.pdf', 'EMSS original paper'),
 ('5', 'T. Saito and M. Rehmsmeier. "The Precision-Recall Plot Is More Informative than the ROC Plot When Evaluating Binary Classifiers on Imbalanced Datasets." PLOS ONE, 10(3), e0118432, 2015. doi:10.1371/journal.pone.0118432.', 'https://doi.org/10.1371/journal.pone.0118432', 'Publisher article'),
 ('6', 'scikit-learn developers. "average_precision_score." API reference. Accessed 2 November 2026.', 'https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html', 'Metric definition'),
]
for number, text, url, label in references:
    p(f'[{number}] {escape(text)} <link href="{escape(url)}" color="#203D58">{escape(label)}</link>.', 'ref')
    markdown[-1] += f'\n{url}\n'

def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#CAD2D8'))
    canvas.setLineWidth(.45)
    canvas.line(50,43,A4[0]-50,43)
    canvas.setFont('Helvetica',7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(50,30,'ATOMIC TRANSFERS AND OBSERVABLE CONCURRENCY')
    canvas.drawRightString(A4[0]-50,30,str(doc.page))
    if doc.page>1:
        canvas.setFont('Helvetica',7.5)
        canvas.drawString(50,A4[1]-32,'BHATIA, KAPOOR AND GARG')
        canvas.drawRightString(A4[0]-50,A4[1]-32,'RESEARCH MANUSCRIPT')
    canvas.restoreState()

doc=SimpleDocTemplate(str(OUT),pagesize=A4,leftMargin=50,rightMargin=50,topMargin=48,bottomMargin=55,
                     title='Atomic Transfers and Observable Concurrency in a SQLite Banking Prototype',
                     author='Harsh Bhatia; Tanisha Kapoor; Prakhar Garg')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
(ROOT/'docs/research/research_paper.md').write_text('\n'.join(markdown),encoding='utf-8')
print(OUT)
