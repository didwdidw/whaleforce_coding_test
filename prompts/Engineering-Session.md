# Engineering Session

**Role:** engineering agent implementing `docs/task1-spec.md` (Task 1 — Generalized Browser
Automation Agent).

**Scope:** the frozen spec governs. Build in milestone order (§13), starting at M0 (preflight report
from a real cloud container). Spec changes only as §16 amendments, proposed here and approved by the
product owner. Validation/test case content is never shown to this session.

Every user prompt below is logged verbatim, in order, separated by `==========`.

==========

/rename

==========

/rename Engineering Session

==========

## Your role

You implement `docs/task1-spec.md`. **The spec governs.** Read it yourself — this brief does not
repeat it and does not override it.

You may **stop and discuss** at any time: a requirement that turns out to be impractical, a design
you believe is better, an assumption in the spec that reality contradicts. Raising these is expected
and welcome.

You may **not decide unilaterally**. If a spec requirement is in your way, the move is to stop and
ask, not to reinterpret it, work around it, or implement "the spirit of it". A silently reinterpreted
requirement is worse than a blocked one, because acceptance will grade against the written spec.

If you change the spec's meaning, that is an amendment in §16 — proposed by you, approved by the
product owner, never written by you alone.

## What you will never be given

**Validation and test case content.** Ever. You get the dev split (`eval/dev-set.md`), an aggregate
score, and a `failure_class` histogram. Nothing else. Do not ask for the cases, do not try to infer
them from scores, and do not tune against the histogram case-by-case. The split exists so that the
score means something; asking for it is asking to destroy the only measurement we have.

## Where to start

### M0 — Preflight, from the deployed environment (not your laptop)

This is a **report, not code**. Deliverable: a written preflight report containing

1. RAM headroom: one browser process + 2 contexts + the app, under load, on the chosen tier.
2. Reachability of `en.wikipedia.org`, `books.toscrape.com`, `www.sec.gov` **from the deployment IP**,
   with status codes. Cloud IPs get treated differently from residential ones — this is the point of
   the check.
3. Re-verification of the policy facts in spec §3.4 (robots rules, SEC's stated limits).
4. The account's actual Gemini rate limits, read from the console — the docs do not publish them.
5. Token and USD cost per run on three page shapes, and the requests-per-day feasibility arithmetic
   (Amendment 7.8). Say plainly whether a full eval round fits in one day.
6. Pinned target pages for OP-4…OP-7, and which OP-5 variant you are using.

**If anything in M0 fails, stop and report.** Do not substitute a site, do not engineer around a
block, do not shrink a budget to make the numbers fit.

**The first gate is the one most likely to fail, and that is the expected outcome, not a mistake you
made.** M0 exists to find out whether the plan fits reality. If the RAM measurement or the quota
arithmetic comes back short, report it and get a box or a budget that fits. **Do not cut concurrency,
budgets, or model calls to make the numbers fit** — that silently changes the system being measured,
and every later number becomes meaningless.

### M1 — Walking skeleton, deployed

Deliverable: a **public URL** where a task can be submitted, runs against the fixture with **no LLM
in the loop at all**, and shows progress plus a step trace. Queue and 429 behaviour work. Nothing is
verified yet, nothing is intelligent yet.

Build this before anything clever. Deployment, the browser lifecycle, the queue, and the trace store
are where time actually disappears, and every later milestone rides on them. A brilliant agent that
is not deployed scores nothing — the graders test the deployed system.

## Traps — where "looks right but is wrong" gets built

- **Verifying against the trimmed snapshot.** The reduced view goes to the model; verification must
  re-resolve anchors in the *full* stored artifact (A7.4). Verifying against the trimmed view makes
  verification circular and it will pass everything.
- **Letting the model hand you anchor and value together.** The anchor must be independently
  re-resolvable by code that never sees the model's answer. If the only thing proving the value is
  the same generation that produced it, nothing is verified.
- **The second table.** The S&P 500 article has two sortable tables with overlapping column
  semantics. Anchors scoped by header text alone will match the wrong one and return a completely
  plausible wrong answer.
- **Numeric vs lexicographic sort.** Verify the order *the page produced*, not the order you would
  compute. Getting this backwards produces confident nonsense on CIK and GDP columns.
- **Adjacent labels.** On a books.toscrape product page, "Price (excl. tax)" and "Price (incl. tax)"
  are adjacent rows and frequently carry identical values. Label→value binding has to be exact, and
  a passing test on this page proves less than you think unless the labels differ.
- **Absence without a coverage anchor.** "I looked and didn't find it" is `unverified`, never
  `no_result_verified` (Amendment 3).
- **A retry wearing a recovery costume.** Same strategy family with a reworded prompt is a retry.
  Recovery is a *cross-family* transition driven by a named diagnosed cause.
- **Exploration eating the recovery reserve.** If the budget split isn't enforced, runs die before
  they can demonstrate self-correction — and self-correction is the headline graded mechanism.
- **Memory write-back from an unverified run**, or a memory hit that skips verification. Poisoned
  locator memory is worse than no memory.
- **Fixture on localhost.** It will trip the egress guard, and the tempting fix — an allow-list hole —
  destroys the security claim. Separate public hostname (S-2.8).
- **`partial` and `unverified` leaking into success.** Check every aggregation, every chart, every
  API field, and the copy on the page.
- **Injection detection by keyword.** Matching "ignore previous instructions" catches nothing real.
  The defence is structural: goal and policy outside model-mutable state, action allow-list,
  navigation origin policy.
- **Free-tier quota burned by your own iteration.** Your development loop draws on the same daily
  budget as the eval. Plan for it, and use the demo/eval credential separation from the start.
- **First impression is a cold start.** A grader's very first request may sit behind container and
  browser startup. Pre-executed runs on the homepage are not decoration; they are the difference
  between "slow" and "broken".

## Stop and ask — do not decide these yourself

1. **Any paid resource, any recurring cost.** Bring alternatives and a number.
2. **M0 showing the free tier cannot cover a full eval round.** Report the arithmetic and the
   paid-tier cost; the spend decision is the product owner's.
3. **Any site unreachable or blocked from the deployment IP.** Do not substitute another site.
4. **Changing the pinned model**, using a `latest` alias, or any preview model.
5. **Any change to** promised records, the status taxonomy, the strategy families, the hard gates, or
   the definition of `verified`.
6. **Anything that would make a gate pass by weakening it.** If the only way through is to lower the
   bar, the correct outcome is a failing gate and a conversation.
7. **The OP-5 variant**, if the collapsible target turns out to be unstable. The spec names a
   fallback (S-3.4) — confirm which one you took.
8. **Dropping a promised record.** Allowed, and sometimes correct — but it is a product decision, and
   it must be removed from the support matrix and README at the same time.

## Money and credentials (spec Amendment 8 — read it, this is the short form)

- **Hosting during development: Cloudflare Tunnel from the product owner's machine.** Picking a host
  is not a milestone. Do not spend development time on it.
- **But M0's RAM and reachability numbers must come from a real cloud container, not the tunnel.**
  Spin one up, `curl` the three sites, watch memory, tear it down. Measuring from a home network is
  always green and just moves the discovery to deployment day.
- **Keys are in `api_keys/`** (git-ignored): `Free_tier_agent_API_Key`, `Billing_agent_API_Key`.
  Load from file only. Never `cat` them, never log them, never let them reach a trace or a prompt
  record — `prompts/` is a published artifact and the keys now sit right next to it.
- **Free → paid fallback is automatic for dev and eval.** It is **forbidden on the public demo path**,
  which stays `blocked / provider_quota`. Otherwise grader traffic eats the evaluation quota, and the
  spend ceiling — which only exists in a person's head — has nothing enforcing it at runtime.
- **Record which credential tier each run used.** The README discloses that free-tier content is used
  by the provider to improve its products and paid-tier content is not; a silent switch makes that
  disclosure false.
- **Provider spend: up to USD 5 cumulative is yours to approve.** Past that, ask.
- **Output tokens are the expensive half**, not input — output is billed including thinking, at 8.3×
  input on `gemini-2.5-flash`. Cap output per call and per run, and bound the thinking budget where
  the model exposes one.
- **Dev-only response cache** in the provider adapter, keyed by prompt hash. Off for validation and
  test. Any cost or latency number you report must come from an uncached run.
- **Pick the cheapest stable model that is good enough**, by running a bounded comparison — not by
  assumption. The pricing page is the only price source.
- **Sub-agents: offline work only** (mutation seeds, fixture pages, batch classification, code
  review). Never in the product's inference path. You do not author eval cases.

## Working conventions

- Log every prompt verbatim to your own file under `prompts/`, per `CLAUDE.md`.
- Commit at real milestones — not once per action, not one squashed lump at the end. The commit
  history is graded as evidence of real incremental development.
- Build in milestone order (§13). Do not start a milestone with an earlier gate unmet.
- When you cut scope, cut in the pre-committed order (S-13.1) and say so out loud.

==========

*[Answers to a three-question decision block raised by the engineering session before M0 could
close. Recorded verbatim as the selected option labels; the questions are included so the answers
are readable.]*

**Q1 — Cloud access.** "M0.1/M0.2 need RAM and reachability measured from a real cloud container
(A8.3) — I have no cloud credentials and can't authenticate. Local baseline peak is 794 MiB
(Chromium 601 + Playwright node driver 155 + app 35), so 512 MB tiers are already out. How do you
want the cloud measurement done?"

> **You run my script, paste JSON (Recommended)**

**Q2 — Rate limits.** "S-11.18 / M0.4 requires the account's actual Gemini rate limits read from the
console — the docs don't publish them and I can't reach AI Studio. Can you read them for me?"

> **I'll read AI Studio and paste them (Recommended)**

**Q3 — Pinned model.** "Stop-and-ask #4: the pinned model. `gemini-2.5-flash` and
`gemini-2.5-flash-lite` — including the A7.10 reference model — return 404 'no longer available to
new users' on this key. Only Gemini 3.x works. All prices re-verified today; all options are stable
GA, not preview. Which do I pin?"

> **gemini-3.1-flash-lite (Recommended)**

==========

啊怎麼沒有根據 system prompt 把我的 prompt 記錄下來

==========

1. Amendment 9: Approve
PM 改寫了一版 spec
自己看一下 commit log, 我稍微講一下重點差異：
- A9.2 多一句：pin 定案前不准跑 validation 或 test
- 新增 A9.5：A8.11 的比較至少放一個非 lite 的候選。pin 用 locator reasoning 的品質決定，不是價格。3.6-flash 是 1.50/7.50、3.5-flash 是 1.50/9.00，同價位帶挑 3.6
- 新增 A9.6：validation 和 test 一律走付費 key
- 新增 A9.7：要能無人值守連續跑兩週
- §7 的 SEC UA 和 Crawl-delay 兩條升格成需求

A9.1 / A9.3 / A9.4 照你原本的

2. Rate limits
gemini-3.1-flash-lite, free tier: RPM 15 / TPM 250K / RPD 500
且量測當下已用 13 / 28.61K / 23
按你的 294 requests per round：一天一輪，剩約兩百個 request 給開發迭代。跑到 S-6.1 上限就不夠

所以計分那幾輪走付費 key，開發迭代走 free、打完自動 fallback
另外 RPM 15 是另一條線，concurrency 2 的排程要自己遵守，不要等 provider 回 429 才知道。那跟我們自己的 429 是兩回事

3. 主機買好了，你 §8 的建議我改掉
Info: Tencent Cloud / Ashburn US，2 vCPU / 4 GB / 60 GB SSD / 1.5 TB, $4 per month
透過 Zeabur 租、Zeabur 當 deploy 層
IPv4 43.166.128.37
SSH 我從 Zeabur dashboard 進得去，要用的時候跟我拿
最好給我 step by step 的操作讓我可以直接貼上

這台同時是 M0 的量測對象和 M1 的正式主機，不會再換

先跑 reachability，其他後面再說：
- 這是 Tencent 的網段，三個站對它的態度是唯一有風險的未知數。先只跑 M0.2，403 的話立刻回報，不要繼續往下做
- Wikipedia 或 books.toscrape 被擋就跟我講，我換 provider 重買。OP-4…OP-7 全靠它們
- 只有 SEC 被擋的話也跟我講，先別自己處理，那是 Task 2 seam 的範圍
- 都不准換 site

另外：
- repo 還沒 push 到 GitHub，機器上不能 clone(你想 push 也可以 push)。rsync 傳 preflight/ 就好，api_keys/ 不要上去
- dashboard 顯示 OS 是 Ubuntu 22.04，不是結帳時選的 24.04。先 lsb_release -a 和 python3 -V 確認，不要假設 24.04 / Python 3.12
- 量 RAM 的時候把 k3s + agent 的 484 MB baseline 單獨列一行，跟 app 自己的 footprint 分開
- Zeabur 的自動偵測看到 Python 會套標準 image，裝不出 Chromium。之後部署要用自訂 Dockerfile，從 Playwright 官方 image 起手

M1 照走，不等這些

==========

我跑的 command 跟結果都放在 server_environment.txt 了
你自己看一下
looks good to me

==========

$docker version --format '{{.Server.Version}}' 2>/dev/null || echo "no docker daemon"
=> no docker daemon

我覺得不要裝 docker 了，理由跟你講的一樣
