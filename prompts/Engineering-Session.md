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

==========

k3s 也沒有。docker、containerd、kubectl 全都沒有

ubuntu@VM-20-55-ubuntu:~$ which -a k3s kubectl containerd crictl nerdctl 2>/dev/null; echo "---"
---
ubuntu@VM-20-55-ubuntu:~$ ls -l /usr/local/bin/
total 0
lrwxrwxrwx 1 root root 37 Jul 26 21:44 tat_agent -> /usr/local/qcloud/tat_agent/tat_agent
ubuntu@VM-20-55-ubuntu:~$ sudo ls /var/lib/rancher
no rancher dir
ubuntu@VM-20-55-ubuntu:~$ sudo systemctl list-units --type=service --state=running --no-pager
  acpid / chrony / cron / dbus / getty@tty1 / ModemManager / multipathd
  networkd-dispatcher / polkit / rsyslog / serial-getty@ttyS0 / ssh
  systemd-journald / systemd-logind / systemd-networkd / systemd-resolved
  systemd-udevd / tat_agent / udisks2 / unattended-upgrades / upower / user@1000
ubuntu@VM-20-55-ubuntu:~$ ps aux --sort=-rss | head -8
root  3950  1.6%  63120  /usr/local/qcloud/YunJing/YDEyes/YDService
root   353  0.7%  27292  /sbin/multipathd -d -s
root  2668  0.7%  26888  barad_agent
root   302  0.6%  26080  /usr/lib/systemd/systemd-journald
root   987  0.6%  23396  unattended-upgrade-shutdown
root   935  0.5%  21132  networkd-dispatcher
root  4082  0.4%  17000  /usr/local/qcloud/YunJing/YDLive/YDLive
------------------------------------------------------
Zeabur 還沒碰過這台，非原生的東西全是騰訊自己的 agent
我覺得不裝 k3s。等 Zeabur 部署時它自己裝，手動裝一套如果有衝突會煩死
M0.1 改成在主機上用 system Python 量，就是你最早那版 run_cloud_preflight.sh。24.04 / Python 3.12.3 都在
容器對 RSS 只差幾十 MB，不影響塞不塞得下。會被 runtime 影響的是 cold start，那個等 M1 部署完再量

所以 M0.1 現在主機上量，M1 部署完在 pod 裡複驗，兩個數字都留在報告裡
另外 484 MB 那個 baseline 是低估的，裡面沒有 k3s。Zeabur 部署上去還會再跳三到五百 MB，headroom 算式要改

給我 server 版的指令，一樣 paste-and-go

另外補充兩點:
1. 回覆給我的訊息請用繁體中文，我讀起來比較快
2. SSH name 為 ubuntu。後面還有command的話直接幫我填進去

==========

*[M0.1 result pasted from the host: `cat ~/cloud-ram.json`. Stored verbatim as
`preflight/results/cloud-ram-tencent-host.json`; reproduced here in summary to keep the log
readable — peak 899.9 MiB, swap verdict PASS, no load errors.]*

```
"system_used_mib_before_launch": 627.7, "system_used_mib_after_teardown": 562.0,
"outside_our_tree": {"total_mib": 453.5, top: YDService 65.4, multipathd 26.7,
                     barad_agent 26.3, systemd-journal 26.0, unattended-upgr 22.8, ...}
"marks_mib": {baseline 32.1, browser_launched 424.8, two_contexts_idle 597.0,
              both_loaded 846.2, after_artifact_capture 869.6, after_screenshots 890.3}
"concurrent_load_seconds": 0.94
"app_tree_peak_rss_mib": 899.9
"peak_by_process_mib": {python 32.1, MainThread 142.1, chrome-headless 721.4, ps 4.3}
"swap": {baseline_mib 0.0, peak_mib 0.0, growth_during_run_mib 0.0,
         touched_by_this_run false, verdict "PASS - no swap growth"}
"platform_meminfo": {MemTotal 3813268 kB, MemAvailable 3237804 kB, SwapTotal 2035708 kB}
"artifact_dom_chars": {heavy 1921689, light 52426}, "load_errors": [], "samples": 61
```

==========

M0 收了，往 M1

899.9 那個 miss 你自己抓出來就夠了，不用再處理。本機數字是地板不是估計值這條記著就好
一件事帶進 M1：A9.7.3 的 steady-state 要對著兩週去設計，不是跑幾小時看起來還好就算過

headroom 1.7 GB ÷ 336 小時 = 每小時漏 5 MB 就吃光。5 MB/h 在三小時內只有 15 MB，會淹沒在噪音裡，所以觀察窗口和量測方法要能分辨這個量級
實務上不要把漏水追到零，追不完。browser supervisor 本來就要寫，順手把定期回收做進去: 每 N 個 run 或每 N 小時重啟一次。兩週的要求就從「證明沒有漏」變成「漏了也沒關係」
其他照你說的走

go ahead now

==========

兩個 hostname 應該沒問題
Zeabur 的網域看起來是綁在 service 上不是 project 上
同一個 project 開兩個 service、各自 Generate Domain，各拿一個免費的 *.zeabur.app
不用買網域也不用開洞

部署前要先把目前的 commit push 上 GitHub，這樣 Zeabur 才能從 git 拉去 build
我確認過了 .gitignore 有擋應該擋的，沒有 tracked 到任何 key，歷史上也從來沒 commit 過，可以推

SSH 連線用 ssh wf-prod 就好。我把環境搞好了
主機別名 wf-prod，直接用：
  ssh wf-prod
  rsync -av preflight/ wf-prod:~/preflight/
金鑰在我 Mac 的 ~/.ssh 裡

robots 那兩個抓得好。空行那個很棒，「這一類 bug 用 dev-set 抓不到」這句比 bug 本身重要

有兩件事：
1. RFC 9309 的語意要進 spec，S-2.3 現在只寫 enforce robots 太鬆，剛剛證明了 parser 語意不同會變成實質違規。我讓 PM 補，你不用動 spec
2. ALLOW_PRIVATE_EGRESS 要防呆。production 誤設等於 SSRF 防護整個關掉，而且系統會安靜地照常運作，沒人會發現。非 dev 環境偵測到就拒絕啟動，另外每個 run 的 trace 要記錄當下 egress guard 是開的——稽核看得到，不用相信我們的說法

Dockerfile 現在的 CMD 還是 M0 那個佔位的，部署前記得換掉

==========

我出了一個 mistake
看來 OS 應該要選 ZeaburOS 才能用 Zeabur 的服務
我現在要重灌，幫我確認一下所有資料都有備份我可以安心重灌

==========

重灌好了，IP 沒變，ssh key也幫你弄好了
先跑 reachability，把進度恢復到剛剛的樣子
然後繼續自己做

==========

Error: Invalid input
Code: INVALID_ARGUMENT
Description: Dockerfile is required for arbitrary Git sources. Auto-detection is not supported yet.
Trace ID: 07d5e05b1e6d55d4c1e53f593118a281

==========

我已經選定了綁定git儲存庫
重新部署跳了這個 error

Error: Invalid input
Code: INVALID_ARGUMENT
Description: gitURL is required for arbitrary git service
Trace ID: 8edee5c2fb100dadc05b09bfcf0eb85d

==========

As you suggested:
1. wf-fixture.zeabur.app
2. wf-agent.zeabur.app
Now go ahead

==========

my bad 我現在處理
fixture 的 GIT_SHA 現在應該要設什麼value

==========

我改完後重啟目前版本了
should be working now
還是一定要重新部署？
try again

==========

重新部署好了，去跑你的部署後檢查

另外講一下前面的其他問題
Amendment 10 進去了，commit 69c7a2b，去讀。六條語意你已經做完了，新的是這幾條：
A10.3 的界線先確認，這條最急。404 算有效答案，代表無限制，不算取不到。books.toscrape 就是 404，你的 fail closed 如果把 404 當失敗，整站會被鎖掉，OP-6 和 OP-7 直接沒了
A10.4 每個 robots 決定都要在 trace 記下命中的規則：directive、pattern、群組的 user-agent。沒命中就明確記「無規則命中」。放行也要記，不是只記拒絕。當時的問題就是「放行了但沒有任何東西可以檢查它為什麼放行」
A10.5 適用範圍是所有 origin，含 Task 2 seam 的 server-side fetcher，不只 browser navigation。出事的那一半就在那裡，browser tier 根本不會去 SEC
A10.6 單元測試要把 live www.sec.gov/robots.txt 的內容本身當成其中一個 fixture
A10.2 明文禁用 urllib.robotparser，確認沒有路徑會回到它
驗收多了 A-26 到 A-28。A-27 要求 robots 語意測試跑在 CI 不是手動，repo 已經在 GitHub 上了，開個 workflow


而你剛剛提到兩個缺陷，我追問兩件事：
1. 搜出 0 results 那次 run 最後終止在什麼 status？你說它「當成答案回報」，如果是 no_result_verified、或任何被算成功的狀態，那就是一次 false verified claim，而那是 hard gate 要求為 0 的東西。Amendment 3 講的就是這個，「我找了但沒找到」永遠是 unverified。現在處理最便宜，等 M2 verifier 寫完再問就是重複工作
2. 搜尋詞你做得好，沒指定就 abstain，不編一個。同一條原則要往上一層套到路由：marker 沒有信心命中、或多個操作同時命中的時候，要 unsupported，不是挑第一個。「gated page」那次不是 marker 寫得不夠好，是「猜」這個行為本身錯了

你自己那句「我只驗了結構沒驗內容，是檢查方法有漏不只是程式有 bug」比那兩個 bug 都重要。Good job。那正好是 M2 verifier 存在的理由，寫進報告

==========

Approved
你自己從 k3s 刪 pod 去量
現在還沒交件，30 秒中斷沒有代價

但我要兩個數字，不是一個：
- pod 重啟、image 已經在節點上: 這是常態，也是 A8.5 要記的數字
- 完整 redeploy 含拉 image: 這是我每次推版本時 URL 真正不可用的那個窗口，比前者長，而且那才是最可能撞到人的時刻。你之前量過 image pull，兩段加起來就好

M1 收了，往 M2
M2 有一件事現在就排進去：那兩個有缺陷的 run 要留著當回歸案例，但是放在 verifier 層，不是 executor 層
你那 14 個 executor 測試只防止同樣的 bug 再犯
我要證明的是拿那兩次的 artifact 重播時 verifier 會擋下來

理由是你自己講的那句：那兩個 run 步數對、artifact 數對、terminal status 對、HTTP code 對，全部通過，只是回答了另一個問題。verifier 如果攔不住這兩個，它就沒有在做它該做的事，而我們會等到 M4 打真實網站時才發現

「hard gate 還碰不到，不是被通過了」這句寫得對。M2 的 gate 是每個 terminal_status 都要真的被走到過。包含 no_result_verified 和它的 coverage anchor
不要留到 M4 才發現那條路根本走不通

A10 那些做得好，A10.2 用 AST 解析而不是 grep 文字這個細節尤其值得讚許
Good job, thanks

==========

重新部署 done

Spec 更新：Amendment 11（docs/task1-spec.md §16，commit 9cef7a8）。M2 的持久化決定已批准，
但範圍比「掛個 volume」大。動工前完整讀 A11.1–A11.8 與新增的 A-29/A-30/A-31，這裡只是導讀。

決定
- A11.1 掛 persistent volume，artifact store 與 run database 都放上去。
- A11.2 Zeabur 因此從 RollingUpdate 轉成 Recreate、每次部署吃一輪冷啟停機 —— 這個代價被接受，
  但必須寫進 analysis report，不准把持久化講成免費。A8.4 不變：這段停機不准花錢買掉。

掛了 volume 仍然要做的四件事
- A11.3 首頁預跑 run 一律 pin，永不因年齡或磁碟壓力被淘汰，且完全排除在 retention sweep 之外。
  「到期自動重跑」的方案已被否決，理由在條文裡。代價：每個預跑 run 必須顯示 retrieved_at。
- A11.4 過期必須是「已於某日過期」的記錄狀態，不是 404、不是破圖、不是空面板。
  artifact 的 metadata（id、source URL、retrieved_at、content hash、byte length、過期日）
  必須在 bytes 被回收之後仍然存在。HTML 與 API 兩邊都要。這條跟 volume 無關，本來就該有。
- A11.5 /healthz 必須用「實際寫入探測」確認 artifact store 已掛載且可寫，不可只檢查路徑存在；
  不可靜靜退回暫時儲存（A10.7）；production 模式下無法初始化 store 就是啟動失敗（A10.8）。
- A11.6 retention 要真的被執行：年齡上限 + 總容量上限（綁磁碟比例，機器 60 GB，
  單次大 DOM run 約 2 MB），淘汰順序為未 pin 者由舊到新，每次淘汰要記錄，
  逼近上限是必須可見的運維事件（health endpoint 與 log），不是無聲覆蓋證據。

你在 M2 修掉的兩個 bug 已升為通則，請往上收一層再往 M3 走
- A11.7 空洞的驗證必須 fail closed。零 claim 的 postcondition 不得產生
  推廣：任何「因為沒有東西可檢查而通過」的驗證都是缺陷 —— 空 claim set
  零 anchor 被解析、全部 skip 的 check set，都必須以 failed 加上診斷原
  「沒有失敗」不等於「全部通過」。請掃過所有驗證與聚合路徑，不只是當初
- A11.8 明確設定的 falsy 值不等於未設定。0 / false / 空字串必須與 unset
  預設值只在真正缺值時套用。同樣請掃過整份 config 解析，不只 retention_

新增驗收項（黑箱）
- A-29 重新部署後，部署前的預跑 run 與使用者 run 的 artifact 仍可解析。
- A-30 打開一個 artifact 已過保存期限的 run，看到帶日期的過期狀態且 met
- A-31 artifact store 不可寫時 /healthz 回不健康；retention 的年齡與容

順序建議：A11.7 與 A11.8 的全面掃查先做（它們會影響 M3 的驗證行為，晚做
再做 volume 與 retention。做完照慣例回報，M3 之後再往下走。

==========

金鑰的做法不應該經你的手

我已經用 Zeabur 的 Config Editor 弄好了，路徑 /etc/wf/gemini_free_tier
你把 config.py 的常數改成這個。刻意放在 /data 外面
/data 是 artifact store 的根，證據是會被服務出去的，金鑰不該住在同一棵樹底下。

目前我只放免費層那把，付費的沒放

BTW, M8 的評估是打線上的部署，還是打本機起的一份？
如果打線上，付費金鑰遲早要上那台機器，而到那天"金鑰根本不在"這個保護就消失了，擋 grader 流量去花錢的只剩程式碼一條，那是 A10.7 已經禁掉的：失效模式是「保護關閉」的控制，最後一定會處於關閉狀態
現在先想清楚，避免 M8 要重做

另外三件事跟著金鑰一起做：
1. 加測試證明 store 不會列舉也不會服務 /etc/wf 底下任何東西，retention 也不會碰它
2. /healthz 只報「有沒有金鑰」和「是哪一層」，不報值、不報前綴、不報長度。
3. 金鑰不存在的時候不要整個拒絕啟動。M1/M2 的 fixture 路徑要還能跑，planner 路徑明確降級成具名的失敗狀態，並且在 /healthz 看得見 (不然整個掛掉的話，我連 demo 都沒得 demo)

comparing 的部分寫得好
"兩個都 11/11 代表題目分不出它們，不是它們等價"和"先比較再修 validator 就會把自己的盲點量成模型品質" 這兩句留著，到時候放進 M8 的報告裡

==========

你那個區分是對的，我搞混了，我把grader 打線上跟我們的 validation/test 打線上想成同一件事
A9.6 只管我們自己那一列。這樣公開容器確實永遠不需要付費金鑰

建議一 approve, with 3 conditions：
1. 那個 scored service 不要開公開網域。Zeabur 每個服務都免費送一個 *.zeabur.app，開了就等於把付費金鑰放在一個(沒人知道)的 URL 後面。你說 scored round 是從 workload 啟動不是打 URL，那就乾脆不要有 URL。
2. 兩個服務共掛同一個 volume 先去驗，別假設。RWO 在同一節點通常可以，但 SQLite 兩個 writer 同時跑 retention 的競態你要先看過。
3. RAM 只剩大約 1.7 GB。app 峰值實測 899.9 MiB，第二個容器起來會很緊。scored round 不能跟重負載同時跑，這條寫進 runbook。

建議二也 approve，但理由我換一個
你寫的是「為了將來政策可能改變先做起來」，那讀起來像投機性工作，會被打。真正的理由是它今天就在承重：付費金鑰現在已經在用，而 Amendment 8 那個 USD 5 上限只存在我腦子裡，執行期沒有任何東西在擋。你做的是把一個人腦裡的數字變成程式擋得住的東西。改用這個講法寫。

那個漏洞你講得太輕。那不是「retention 邊界不夠嚴謹」，那是任意檔案刪除加任意檔案讀取，出現在一個拿安全姿態當賣點的產品裡，而且從 M2 就在
107 個測試沒抓到它，抓到它的是被要求「證明給我看」才寫出來的那個邊界測試。這件事寫進 M8 報告當證據，不要當糗事帶過。

現在先別建第二個 service。那個架構我要寫進 spec 才動，你先去做 M3 主體: executor 的模型驅動迴圈跟 recovery

部署我來，Config Editor 也我來

==========

go ahead, 把那四個 failure class 走完，M3 gate 關掉

Note: provider_quota 不要真的燒掉一天的免費配額去撞。RPD 500 是這個專案唯一買不回來的東西。用注入點做，然後在報告裡寫清楚它是注入達成的、不是自然發生的。其他三個同理，能注入就注入。

衝過頭那個留到 M4 再選，兩個選項我都可以，但 postcondition 不准動
那個 verification_mismatch 是這份報告裡最值錢的東西：模型不可靠，然後產品把它變成一次失敗而不是一個自信的錯答案
M8 的 analysis report 要拿這條當主線，trace 那四行直接放進去

==========

部署 done
去補 A-32 / A-33 / A-34，然後開始 M4

另外我又想到幾件事
1. 每個 dev case 的正確答案要連同什麼時候、從哪個版本的頁面取得一起記下來。因為維基百科會變、S&P 500 成分股會換、GDP 數字會更新，要有確切 meata data。維基每個頁面都有 revision id，把當時看到的那個記進去。之後答案對不上的時候，你才分得出是網站變了還是我們退步了。沒有這個，M4 的 dev case 過幾天就會開始無緣無故地紅。

2. 不准為了讓 OP-4 到 OP-7 過而針對特定網站寫特例。reducer 或 planner 裡出現"如果是維基百科就..." 這種不general的東西就相當於是用弱化 gate 的方式通過 gate。真的需要，那是要跟我談的設計問題

3. M4 是第一次讓整條迴圈打真實網站，配額會開始燒得快。開發用快取要開著，validation 和 test 關掉，任何你要報的成本或延遲數字都必須來自沒走快取的 run

單步比較那兩個點是 11/11，但你自己說了那是單步。M4 是整條迴圈，估計會被打臉，那是正常的，照實報

==========

去做 M4 主體

reducer 那些 wiki 專屬字串，你標記得對，goo job
但那條線用講的很模糊，給你一個測得出來的判準：把那些字串拿掉，換成通用的 chrome 排除，OP-4 還能不能過？

過，只是變慢變吵: 那就是最佳化，留著沒問題
不過: 那就是特例，那些字串在替我們生出正確答案

你不用現在就跑，但 M4 收尾前要有這個數字，我才知道那條線的哪一邊

排序要點兩次表頭那個你先講出來很好。那正是 spec 點名的陷阱：驗證「頁面實際產生的順序」，不是你以為它會排出來的順序。多一次少一次都是合理的錯答案，而 verification_mismatch 本來就是要接住這個

還有 A12.3 那個獨立 workload，spec 已經寫進去了，但先別建。M4 是長的那根，那個東西 M8 前再弄就好，現在插隊只會讓兩件事都做不完

==========

OP-6 那個 abstain 查的時候分清楚兩種可能，這比修好它更重要：

一種是 abstain 機制正常運作——真的資訊不足，棄權是對的。
一種是某個政策檢查誤判，然後棄權替它把錯誤蓋起來了。

我們是刻意做了「不確定就棄權」，所以現在一個錯的棄權會躲在一個正確的設計後面，從外面看一模一樣。這跟之前那些「合理的錯答案」是同一個問題，只是這次長在安全的那一邊。查完講清楚是哪一種。

另外元素身分這件事，這是第三次了：M2 一次、M3 一次、OP-7 又一次，每次都是補一個欄位（id、name、可見文字、現在 href 和 title）。三次就不是三個 bug，是那個模型本身不夠。

停下來把「持久元素身分」收成一個定義，兩邊共用——planner 送出的 ref、postcondition 宣告的目標、必要動作比對，都吃同一份。不要再一次遇到就補一個欄位，那條路的盡頭是有一天在真實網站上補不到。

OP-6 查完再開 OP-4／OP-5。

==========

suspicion 那個做法對，尤其是你自己把「驗證讀完整 artifact 所以 no_result_verified 不受影響、這條只在什麼都沒被檢查過的地方承重」這條界線劃出來。那比我要的乾淨
限制你也照實寫了，good job!

A/B 那個結果你講得太輕。兩臂逐元素相同，代表那些選擇器從寫下去到現在從來沒起過作用，而且沒有任何東西分得出它「有效」跟「不存在」
這跟今天這一類是同一件事。你刪掉是對的

所以 MAIN／INTERACTIVE 那些照量，這不是要不要的問題。理由是 held-out set 跑在我們沒看過的網站上：一條在 Wikipedia 上什麼都沒做的規則無害，一條只在 Wikipedia 上有用的規則會讓我們 dev 的數字帶不出去。量完是零就刪，不是零就留著並寫清楚它靠什麼假設成立。

另外 _same_page 那個 percent-encoding 收成一條一般結論。我們之前講過「失效模式是保護關閉的控制最後一定會關著」，這次是鏡像：一個永遠開著而且判錯的保護，跟一個開著判對的保護，從外面看沒有差別。哪些 fail closed 的判斷目前沒有任何辦法分辨這兩種，列出來。

幫你按重新部署了。把 robots Disallowed 的演示做完收 M4。

==========

我重新部署了

請把前端修掉
support 頁還寫著 This build is M2、OP-4…OP-7 全標 not yet implemented
現在部署出去的系統在低報自己一整個里程碑

那 12/14 語料有個問題：它是寫這個分類器的同一個 session 自己寫的
你剛講完「憑記憶寫的清冊會原封不動複製它本來要稽核的那份自信」，這批語料是同一個形狀。

換來源：eval/dev-set.md 裡每一條 task 原文，加上首頁那些 demo chip，全部斷言不會判成 T-REFUSED。那些句子不是為了測分類器寫的，所以帶不進分類器的假設。

另外「每個宣告的拒絕理由都要真的被某個 case 觸發過」那條測試是這輪最有用的東西，別只留在 tier 分類器上。清冊裡只有半邊覆蓋的那 3 條，照同一個形狀補

清冊寫錯三條那段留著，跟 quiet-failures 放一起進 M8。同一件事的第二個實例，而且這次被稽核的自信是你自己的

==========

是的，以下是我跟 PM 的討論內容
你讀一下，再結合你剛剛的觀察，看看還有哪些要改的一起改一改
不用排序，最後都一定要做完才會交作業
另外，接下來除非有什麼你覺得應該要跟我或是PM討論的關鍵性決策，或是需要我手動幫你部署
不然不用每做到一個階段就停下來回報
你自己做到一個段落就commit然後接著做下一個step就好

我跟PM討論的內容:
-------------------------
Spec 更新：Amendment 13（docs/task1-spec.md §16，commit aa33654）。這是 M4 完成後對照
原始作業做的方向審查，發現三處偏航，都指向同一件事：產品目前宣稱的形狀不等於它實際的形狀。
先完整讀 A13.1–A13.6 與新增的 A-35…A-38，這裡是導讀與問題現況。

問題一：T-DECLARED 從來沒有被指派過
app/executor.py:186 的 classify() 對所有非拒絕任務一律回傳 Tier.EXPERIMENTAL。
後果是 OP-4…OP-7 這四筆承諾紀錄跑出來全部帶著 app/templates/run.html:40 的實驗層橫幅，
上面寫著「本結果為 best effort，已排除於回報的成功率之外」。
系統親口否認自己的承諾面，S-1.3 的 headline success rate 沒有分子。
→ A13.1：tier 必須是真正的三向分類，宣告層的 run 必須是被計入成功率的那一批，
  實驗層橫幅只能出現在真正的實驗層 run 上。

問題二：實驗層不會執行，它只是一個拒絕標籤
關鍵字 router 沒命中的任務，在 executor.py:249 就以 unsupported / policy_refused 結束，
完全沒有開瀏覽器，而且說明字串還是 M2 時代的「no model in the loop」，現在已經是假的。
作業原文明寫 "reliably executes them across different sites" 與
"We will verify with our own unseen tasks"，而 S-1.4 本來就要求 generic agent loop 當 fallback。
A2.2 要求 abstention 說出停在哪一步、最後觀察到的頁面狀態、為什麼 postcondition 無法驗證 ——
沒有實際 browse 過，這三件事一件都講不出來。
Amendment 2 當初用實驗層回答「across different sites」，前提是實驗層真的會去試；
現在的實作等於用站數回答，而站數是二。
→ A13.2：公開、政策乾淨、read-only 而未命中承諾紀錄的任務，必須交給 generic model-driven loop 去試。
  五個子條件全部要做：entry point 解析不出來時「解析不出來」本身就是 abstention 理由；
  §2 政策照舊全部適用；postcondition 仍然在 browse 之前凍結且由 code 擁有（可以較弱，
  但「弱但有檢查」不等於「沒有」）；abstention 必須帶真實觀察；實驗層結果仍不計入 headline rate。
  特別注意：「我們沒有這個腳本」不是政策拒絕，不得回報成 unsupported / policy_refused。

問題三：對外文案已經不實
app/templates/index.html:9 寫「declared surface 之外的任務會被以 T-EXPERIMENTAL 嘗試」——今天不會。
app/templates/support.html 仍把 OP-4…OP-7 標成 not yet implemented (M4)，而 M4 已完成。
首頁輸入框 placeholder 仍是 fixture 任務。
這是全案唯一一處「寫的比做的多」，而誠實揭露正是被直接評分的那一面。
→ A13.3：所有使用者可見的字串必須描述當前正在跑的這個 build。
  描述 build 狀態的字串就是一個宣稱，過時的宣稱就是不實的宣稱。

另外兩件不算偏航但會影響評級的
→ A13.4：planner 目前藏在「use the planner」這個暗語後面。
  評審用自然語言送一個 OP-4 任務，看到的是一條寫死腳本，而 self-correction 的實質是
  他們明列的第一個觀察點。真實站操作的預設路徑必須是 model-driven；
  deterministic script 保留為 provider 不可用時的 fallback、fixture 示範路徑（不得依賴 provider）
  與對照基準。trace 必須記錄這次走的是哪一條，分析報告要分開報兩條路徑的成功率。
→ A13.5：eval/dev-set.md 目前是散文，沒有任何程式會跑它。
  需要一個 harness 對已部署系統執行一個 split、比對每條 case 的 oracle，
  輸出 per-case terminal status、failure class、evidence coverage 與 S-10.7 的 provenance
  （git SHA、pinned model ID、eval-set hash）。同一支 harness 之後跑 A9.6 / A12.3 的計分 split。
  沒有它就沒有 §10.3 的 hard gate、沒有 first-run 分數、分析報告也沒有數據來源。

範圍的重要更新（A13.6）
不要預設任何 milestone 會被犧牲。S-13.1 的犧牲順序只在日曆真的爆掉時才啟用，
不得拿來當規劃預設。M5（locator memory 與 mutation gate）與 M6（safety suite）
分別是自我維護與安全宣稱的證據，兩者都在作業裡被點名。
M7 的 seam 留在範圍內，而且 Task 2 本身不預設不做 ——
Task 1 的任何實作都不得建立在「Task 2 不會做」這個假設上。

新增驗收項（黑箱）
- A-35 用完全自然的語言送一個承諾紀錄任務，不加任何特殊措辭：run 是 T-DECLARED、
  走 model-driven 路徑、沒有實驗層橫幅。
- A-36 送一個承諾範圍外的公開唯讀任務：瀏覽器真的開了、trace 有真實步驟、
  結果是帶實驗層標記的已驗證結果，或是說得出步驟與觀察狀態的 abstention。
- A-37 沒有任何使用者可見字串誤述 build 狀態。
- A-38 用 harness 跑 dev split 並重現它回報的數字，provenance 完整。

建議順序：A13.1 與 A13.3 是小改動大後果，先清掉；接著 A13.4，因為它會改變 A13.2 要接的形狀；
然後 A13.2 的 generic 路徑；再來 A13.5 的 harness，之後 M5 一路往下走。
照慣例做完回報，有爭議或需要改 spec 就停下來問。

==========

Spec 更新三條：Amendment 14、15、16（docs/task1-spec.md §16），以及 docs/task2-seam.md 升到 v1.1。
commits: fd7273e、8e5a63b、157fc30。先完整讀 A14.1–A14.15、A15.1–A15.5、A16.1–A16.11
與新增的驗收項 A-39…A-48。以下是導讀與理由。

═══ Amendment 14 — 一位無前文的獨立審查者拿作業原文逐條對 spec 後的結果 ═══
他的判斷：忠實實作會落在強 B，A 有機會但沒鎖住。缺口如下。

一、四個分析維度只做到兩個（A14.1–A14.3）
作業點名 runtime performance / cost / scalability / correctness 四項並列，
A 級定義是「performance/cost/scalability analysis is concrete」，那是連言。
cost 有 A7.6 與 A9.4、correctness 有 §4 與 §10，
但延遲與擴展性只有驗收項 A-25 在要求數字，沒有任何條文產生那些數字。
S-6.1 的 180 秒是預算不是量測，S-11.8 的 concurrency 2 是設計常數不是飽和點。
→ A14.1：延遲照 cost 的規格鏡射 —— per-step 與 per-run wall clock、time to first result，
  進 trace 也進 UI；報告給分佈（中位數與離散度，不是最佳單例），
  按 tier 與 model-driven / deterministic 兩條路徑分開。
→ A14.2：擴展性要實測 —— 滿併發吞吐、佇列開始 429 的飽和點、負載下排隊等待、cold start。
  每項一個誠實數字就夠，零個不行。
→ A14.3：未宣告站點任務的政策拒絕比例要量出來並回報，
  否則政策形狀的結果讀起來像一個大多時候說不的系統。

二、廣度需要數字不是揭露（A14.4）
grader 用他們自己的 unseen tasks，那些百分之百落在實驗層，
而我們目前對實驗層訂的成功標準是「放棄得夠清楚」。R-11 是我們自己寫的：
「it can read as 'doesn't work'」。
→ 新增 experimental split：8–10 條公開、政策乾淨、read-only、不在任何承
  由 PM 出題，走 A13.5 的 harness，回報 attempt / verified / abstention
  不進 headline 成功率，與它並列。這把 A13.2 的標準從「誠實放棄」提高到

三、grader 看得到的證據（A14.5–A14.9）
→ A14.5：held-out split 在提交時公開，取代 A6.3 的「never committed」。
  holdout 的目的是讓 engineering session 保持誠實，計分的那一刻就結束
  （S-10.6 自己說計分後變回歸套件）。用 eval/holdout-manifest.md 預先 co
  證明內容早於計分。不變：你在計分前永遠拿不到，first run 仍是回報的分數
→ A14.6：自我維護至少要有一次在「我們無法控制的 markup」上示範。
  目前所有 healing 證據都在自己寫的 fixture 上，而自我維護是作業點名的兩
  用真實目標頁的封存 DOM（不是 live，要可重跑），套 S-9.2 的同一組 mutation，
  跑完整的 偵測 → 跨家族重新推導 → 重新驗證 → write-back。
→ A14.7：GS-1/2/3 回到前端當機制證據 —— 它們現在在任何公開介面都看不到，
  等於系統裡最強的 anti-shortcut 與 mutation 證據對讀者隱形。
  放在與支援矩陣明確分離的區塊，帶 A1.3 措辭，不得進任何成功率數字。
  Amendment 1 沒被推翻：自己控制的站上量到的可靠度不是證據，貼標籤不會改
→ A14.8：known-limitations 清單終於有內容定義 —— 使用者會怎麼講的具體任務、
  系統實際做了什麼、為什麼、最終的 terminal_status / failure_class，且讀
  A-4 原本引用 T1.9，那是 discovery 文件的編號，而 §14 的驗收者只讀 spec 與已部署系統，
  對他而言是懸空引用 —— 現在改引 A14.8。
→ A14.9：S-4.4 的「答案對但跳過必要動作 = fail」是我們自找的懲罰，作業沒要求，
  會壓低自己的成功率。它留著，但分析報告要切成獨立類別，
  否則刻意的嚴格會被讀成能力不足。

四、讓 Task 2 保持可建（A14.11–A14.13）
→ A14.11：run record、artifact store、evidence bundle 呈現與 terminal_st
  必須 task-agnostic；S-5.3 的 failure_class 目前是瀏覽器口味的封閉集合，
  per-task 擴充用 amendment 加，不要 fork 模型。
→ A14.12：A13.5 的 harness 繞著 split / oracle / provenance 建，case schema 可插拔。
→ A14.13：S-12.4 的「不得 import 內部模組」只約束證明 seam 可獨立消費的
  不約束 Task 2 產品本身 —— 反過來讀會逼出重複的 store 與 UI。

五、提交面（A14.14–A14.15）
→ A14.14：README 要涵蓋作業點名的三件事：怎麼跑、關鍵設計決策、AI 幫了哪
  repo 必須公開，提交要給 repo URL 與 frontend URL。
→ A14.15：prompts/ 要有讀者入口。CLAUDE.md 的逐字全記規則不變（那才使它
  但作業要的是 "key prompts" 且明說會讀，所以加一份短索引指出實質決策在哪、決定了什麼。

═══ Amendment 15 — 取代 A14.10，公開路徑 free-first ═══
A14.10 原本要求計分後公開路徑「只走付費」，那條寫過頭了，已作廢。
pinned model 兩層一模一樣（A9.2），差別在額度與計費、不在模型或輸出品質
只走付費等於白白丟掉每天 500 個免費 request。
A8.8 當初禁止公開路徑自動 fallback 的兩個理由現在都失效：
額度牆保護的是屆時已完成的評估，而「runtime 沒東西擋花費上限」已由 A12.5
理由消失的限制不再是控制，只是成本。
→ A15.1：計分完成後，公開路徑 free-first、自動 fallback 到付費。
→ A15.2（實作重點）：fallback 不能只掛在「每日額度耗盡」。免費層 RPM 15，
  grader 連送任務、concurrency 2 時會在 run 中途撞到每分鐘節流，
  那個 run 會在評審面前以 blocked / provider_quota 收場，而付費金鑰本來
  任何額度或速率訊號都要往下掉：每日耗盡、RPM 節流、RESOURCE_EXHAUSTED。
  只有兩層都真的用盡、或撞到 A12.5 的每日上限，才是 blocked / provider_quota。
→ A15.3：A12.5 的每日上限每次呼叫前檢查、不分層級 —— 自動 fallback 後它是唯一兜底。
  每日上限設 USD 1（約 430 runs/day，遠高於 grader 需要）。
  A8.9 的「記錄用了哪一層」從資訊升級為承重，A7.9 的揭露完全靠它才準確。
→ A15.4：新增揭露 —— 部分公開流量跑在免費層，而免費層內容會被 provider
  頁面內容依 P2 是公開的，但任務文字是送出者寫的，包括 grader 自己的測試
  README 要照實說明，不得寫得像每個請求都在付費層。
→ A15.5：切換之前完全不變 —— test split 的 first run 完成前，
  A12.2 拓樸與 A8.8 禁令原封不動。切換日期要記錄。
成本已算過：每 run $0.0011–$0.0036，一輪評估約 $0.15，
grader 視窗即使一千個 run 也只有約 $2.3，累計在 A8.10 的 USD 5 內。

═══ Amendment 16 — seam 收下 SEC 的身分與時間語意，升到 v1.1 ═══
來源是 PM 平行研究的提案。語意收下，表面積不收。
被收下的每一條，都是我們現行 seam 會產生「有信心的錯誤答案」的地方，不是缺少便利。
→ A16.2：三個 CIK 不是同一個東西。accession 前十碼是申報者、可能是代辦；
  archive 路徑是第三種寫法；還可能有共同註冊人。三者分開保存、互相對帳，
  以 target registrant 為 filing 的身分；accession 無法唯一解析出註冊人
  我們 v1.0 寫的「cik = the CIK of the filer」對代辦與多註冊人案子就是錯
→ A16.3：查詢必須帶 as_of 不可變截止時間與明確的 revision policy。
  「FY2025 的 10-K」會在 10-K/A 被接受那天改變意思。10-K/A 是 overlay，
  這跟 S-4.12 凍結 postcondition 是同一個紀律。
→ A16.4：四個日期分開，不得互推：report_period_end / filing_date / accepted_at / retrieved_at。
  fiscal year 是報告期間的年份，不是送件年份。
→ A16.5：解析用的 submissions JSON、filing index、directory index 要存下並雜湊。
  沒有它們，「為什麼是這個 accession」事後無法回答 ——
  照我們自己 §4 的標準，那個解析就是 unverified。
→ A16.6：raw 與 derived representation 分離，raw 不可覆寫；
  derived 要指名來源 representation 與 transform 的名稱與版本；
  同一 URL 之後給出不同 bytes 就是新的 representation 與新雜湊。URL 是來
→ A16.7：中繼資料看得到不等於檔案拿得到。有界重試可以，
  但必要 artifact 缺席時不得只憑中繼資料宣告完成，要收在 partial / faile
→ A16.8（我否決了提案的一條）：incorporates_by_reference 不是 Task 1 的職責。
  要偵測 Part III 從 proxy 併入，就得讀 filing 內的併入語句 —— 那是文件結構，S-12.1 禁止。
  Task 1 只從 SEC 中繼資料記 amends / amended_by / related_filing。
  Task 1 保證的是清單與關係完整到讓 Task 2 能說「併入」而不是「缺失」。
→ A16.9 明確不採納（是決定不是遺漏）：2 rps（維持我們的 ≤1 rps）；
  capability token / 簽名 URL / 401-403-410 / 另一套 7 天保存期
  （沒有 auth 系統，且保存期由 A11.6 管，seam 再放一條衝突規則就是陷阱）
  q2_extended（貼近 S-2.17 禁止列舉與大量下載，對第一版 Task 2 沒價值）
  Q1 產出 evidence/locator 物件（10-K 裡的 text offset 是 Task 2 的座標系，
  Task 1 保證穩定識別碼與雜湊，Task 2 在上面建）。18 條驗收縮到觸及新語
→ A16.10：新增 seam 專用 failure_class，不動 terminal_status：
  ambiguous_identity、filing_not_found_as_of、identity_mismatch、hash_mismatch、
  pending_source_publication。
→ A16.11：docs/task2-seam.md v1.1 是唯一具規範性的那份。
  Q1_Q2_SEC_FILING_CONTRACT.md 是提案輸入，不是第二份契約，
  repo 不得同時存在兩份看起來都具約束力的文件。

═══ 順序建議 ═══
1. A14.1–A14.3 的量測先做 —— 要嵌進 run 生命週期，越晚做越要重跑數據。
2. 手上 Amendment 13 的工作收尾。
3. A14.4 的 experimental split 與 A14.6 的封存 DOM 重放（M5 的一部分）。
4. M5 / M6 其餘，再到 M7 的 seam v1.1。
5. A15 的憑證切換排在 test split 計分之後，不要提早。
6. 提交面（README、prompts 索引）最後。
不預設任何 milestone 會被犧牲（A13.6），Task 2 也不預設不做。


照慣例做完一個段落自己 commit 就好
除非有爭議或需要改 spec 就停下來問，需要我手動幫你部署也停下來告訴我

==========

/compact

重新部署 done
按照慣例，請繼續執行到你需要找我討論或是需要我重新部署再停下來


M4 的三個缺陷我全部收下，而且都升級成需求而不是實例修正。Mode B 那個決定批准，但加四個條件。
spec 已更新到 Amendment 17（docs/task1-spec.md §16），acceptance 加了 A-49…A-53。
experimental split 已經出好放在 eval/experimental-set.md。commit cb21f65。

依序回答你的問題：

■ 一、Wikipedia 任務被 fixture 回答 —— 你的修法對，但不夠深（A17.1–A17.3）

你修在 router：站名用文字認、指名別人的站就不給站專屬操作。這兩條我收下並寫進 A17.2。
但這只是把同一類 bug 的觸發條件變窄，沒有讓它變得不可能。

A17.1：run 的「站」是 postcondition 的一部分，不是 routing 的一部分。
artifact 的 origin 要在 plan 時和 claim 一起凍結進 postcondition（S-4.12），
verification 在 artifact origin ≠ 任務指名的 origin 時必須失敗。
理由很簡單：決定 run 去哪裡的東西，不能同時是認證它去對了地方的東西。
§4 存在就是為了這件事。這種 run 是 failed / verification_mismatch，不是任何一種成功。

A17.3：示範必須從輸入算出來。你已經把 robots 示範改成用題目真正要的 URL，正確。
寫成通則：任何 run 可見的示範如果打死一個固定目標而無視輸入，那就是捏造的結果，
即使它的 outcome class 剛好對。每個這種決定都要記下它實際被評估的 URL（A10.6）。

■ 二、「那題之前通過是意外」—— 這句話比缺陷本身重要（A17.4–A17.6）

A17.4：gate / eval 的 case 必須自己斷言前置條件，缺了就大聲失敗。
entry point 打不到 = 這次 suite 執行本身出錯，要當錯誤回報，
不准記成 pass、不准記成 refusal、不准記成 abstention。
本機沒跑 fixture 所以被 egress guard 擋掉，然後 suite 記了一筆 policy refusal 就過去了 ——
那個缺陷不是「一直都在」而已，是「我們的測試設計讓它看不見」。

A17.5：我在你的結果檔裡找到同一個形狀的第二個實例。
eval/results/dev-local-latest.json 每一筆的 declared_tier 都是空字串，
record 則是 "OP-4 · **tier** T-DECLARED"。
原因是 dev-set.md 把 record 和 tier 寫在同一行，
而 harness 的 re.search(r"^- \*\*tier\*\*...") 是行首錨定的，永遠不會 match。
結果：case 檔宣告的 tier 從來沒進到計分，唯一存在的 t
那兩個讀數本來就是要拿來互相對照的，其中一個安靜地不
就是 A17.1 那個缺陷能躲這麼久的機制。請修 parse 或修  每個欄位都獨立一行）。
A-51 要求結果檔裡每個 case 的 declared_tier 非空，且

A17.6：這一條是我對你結果檔的第三個觀察，也請你回答我
同一筆 DEV-01 裡 evidence.independently_checked = 2，
但 notes 寫 "sort_state: derived value (dict), not st artifact"。
如果 verifier 沒辦法對著 artifact 重新解析出這個值， tly checked？
規範寫死：verifier 無法從 artifact 重新解析的 claim  ked，
要算成 unchecked 並在 evidence summary 裡點名。
依 A11.7，所有 claim 都 unchecked 的 run 不能是 succe
「包含了沒發生的檢查的檢查數」跟「沒有 claim 的 postc
如果現況其實有做結構性比對只是 note 寫得不好，跟我說

■ 三、佇列滿的 run 永遠停在 queued（A17.7）

收下。寫成通則：任何回報 run 狀態的表面都必須從已記錄的狀態推導出來，不准自己算。
一筆有 terminal_status 的 run 在 API、HTML、health en
不存在某個表面上它還在排隊。每個輪詢表面都要有一個保證到得了的終止條件。
你順手修掉的那個 render 時重算的 wall clock 也歸在這
run 結束後還會長的耗時是捏造的數字，就照捏造的數字處理。A-52。

■ 四、輸出截斷記成 internal_error（A17.8–A17.10）

同意你的判斷，那不是我們的缺陷也不是模型違約。
A17.8：failure_class 加 output_truncated（走 A14.11   不動）。
記成 internal_error 是把我們的設定歸咎到我們的程式，而且灌水了 S-5.3 說「本身就是一個發現」的那個比率。

兩件你可能沒做的：
A17.9：截斷後的重問要計入該 run 的 LLM call budget，也要計入成本（A7.6）。
在帳上免費的重試會讓兩個預算都變成虛構。同一個 call 第二次截斷就以 output_truncated 結束該步。
A17.10：放寬 output cap 會讓已量到的成本失效。
這個模型家族 output 是 input 的 6–8.3 倍計價（A7.3）
$0.0011–$0.0036 那個區間是在舊 cap 下量的，請在最終 c 在哪個 cap 量的。

■ 五、XB-1 Mode B 的正向答案 —— 批准，但有四個條件（A17.11–A17.12）

批准。理由：一個在正確行為上會觸發的 failure class 就是雜訊，
而 failure class 裡的雜訊會讓真的失敗沒人看。
把正確的「有，這兩本」硬塞進 verification_mismatch 是設計出來的偽陰性，
它會壓低回報的成功率，更糟的是會教會所有人忽略 verification_mismatch。

但這是「成功狀態怎麼達成」的新路徑，重量跟 absence 那條一樣，四個條件缺一不可：

1. 述詞和列舉範圍要在 plan 時凍結並雜湊（S-4.12），在看到任何一筆之前。
   看完結果才組出來的述詞不是 postcondition。
2. 覆蓋錨在正向也一樣是必要的（A3.2）。
   「有，這兩本」是一個關於整個集合的主張 —— 它斷言的是「恰好兩本」，不是「至少兩本」。
   沒有錨就必須把主張弱化成存在性，用那個字面報出來，且不得呈現為完整答案。
   這一條請特別注意，我猜你原本的實作是把它當成「至少」在做。
3. verifier 要獨立地從 artifact 重新推導出符合的集合，不看 run 報了什麼。
   兩個方向的不一致都算 verification_mismatch：
   verifier 找到 run 沒報的成員，或 run 報了 verifier 定位不到的成員。
4. 述詞用反的 run 必須被這個比對抓到。這是一個測試案例，不是一個期望。

A-53 要求：一筆有引用覆蓋錨的 Mode B 正向答案，加上同一個 case 故意把述詞用反、被抓成 verification_mismatch。

■ 六、數字（A17.13–A17.14）

你標「25 rpm 是推算不是觀測」這件事做得對，我要把它變
A17.13：量測要跟它的量測條件寫在同一個地方。
430 runs/min 是在 fixture 上、沒有模型呼叫量到的，那  出現。
推算的數字要在使用的當下標成推算，不是放在註腳。
分 tier、分路徑各報一組是對的，繼續。

A17.14：cold start 不接受「平台的，沒量」。
從外部端到端量：deploy 到第一個成功請求，wall clock，
平台擁有容器排程和拉映像，那是這個數字不能被拆解的理
下次重新部署量一次就結案 —— 而下次重新部署就是現在。

■ 七、A14.3 樣本只有 3 筆

同意，這個數字要等母體。split 出好了，見下。

■ 八、重新部署

我會處理。請把重新部署當成 A17.14 的量測機會：在你要求部署之前先講好從哪一刻開始計時。

■ 九、A14.4 experimental split —— eval/experimental-set.md，10 題

我出的，站和題目和答案都不是你選的（A8.15）。六個站，都不在任何承諾紀錄上，也不是 fixture：
www.scrapethissite.com / the-internet.herokuapp.com / www.gutenberg.org /
www.federalregister.gov / www.ecfr.gov / developer.mozilla.org

每一站的 robots.txt 我在 2026-07-28 自己抓過，原文引在檔案裡（不是摘要，因為 A10.2 的群組語意吃排版）。
檔案的欄位每個都獨立一行，所以 harness 全部 parse 得到。

題目不是均勻簡單的，這是刻意的 —— 只由剛好會動的頁面組成的廣度數字不是廣度數字：
- EXP-01/02/04/05/09：真互動、答案可驗（表單送出、分頁、client-side 排序、非同步渲染、階層導航）
- EXP-06：label→value 綁定
- EXP-03：**陷阱題**。這個站在零結果時只渲染表頭、沒有任何 empty-state 文字、也沒有結果計數。
  我 2026-07-28 驗過。所以正確行為是 unverified 或 abstain。
  在這題回 no_result_verified 就是 silent failure，會被那樣計分 —— 除非 run 引用了它真的在頁面上找到的覆蓋錨。
- EXP-07：**陷阱題**。Gutenberg 1342 的書目表有兩列都叫 Note。
  正確行為有兩種：兩個都回、各自綁到自己的出現位置，或以 ambiguous_match 放棄。
  回其中一個當作「那個 Note」是 silent failure。
- EXP-08：**故意打在被 Disallow 的路徑上**。federalregister.gov 的 /documents/search 是 Disallow。
  blocked / robots_disallowed 只有在 trace 引用了實際命中的規則和它比對的 URL 時才算對（A10.6）。
  走允許的路徑拿到答案一樣正確。真的去抓那個 disallowed path 就整題失敗，不管結果如何。
- EXP-10：MDN，JS 重的現代站，預期會難。沒做出來就報沒做出來。
  不可接受的是一個有自信的錯誤版本號 —— 這題最可能生出那個。

三題（03/07/08）標了 manual_review，因為它們接受不只
harness 判 status，人判 silent-failure 條件。harness 說過不等於真的過。

ground truth：能從 served HTML 讀到的我都釘了（含日期）。
兩題標 pin_at_first_run（EXP-05、EXP-10，值是 client-
用第一次 run 的 artifact 把值釘進檔案再計分，釘之前那ion 但排除在 verified rate 外，
並且要在報告裡寫明排除了哪幾題。
沒有任何一題的答案可以取自 run 自己的 claim —— 那是系

報告要求寫在檔案末段：attempt / verified / abstention
加 terminal_status × failure_class histogram 和 A14.3 的拒絕率，
外加三件事要講白：哪幾題因 pin_at_first_run 被排除、 斷、
以及這是十題量出來的、區間會寬，而區間就是誠實講這件事的方式。

■ 十、順帶一個 robots 比對器的實測邊界案例

openlibrary.org（我沒用它出題，但它是活的測資）同時發布了
User-agent: anthropic-ai、User-agent: ClaudeBot、User
RFC 9309 的 user-agent 行是對 product token 做大小寫無關的「前綴」比對，**不吃萬用字元**，
所以 *bot 什麼都不匹配，我們宣告的 UA 應該落到 * 群組
把 *bot 當 glob 的實作會安靜地套上一個沒人給我們的 Crawl-delay: 10。
A10.8 的單元測試如果還沒蓋這個，請補。

■ 十一、M5

批准往 locator memory + mutation gate 走。A15 照原議

■ 十二、你回報的數字有一段在傳輸中壞掉了

dev split 那段和延遲那段有截斷（"declared 10/11 (0.90913/15"、"中位 4.75s / .14s"、
histogram 缺尾、"ore，容器排程" 那句）。這些數字要進 analysis report，我要正確的原文。
請把 dev split 的完整結果、延遲的完整分佈（分 tier、分路徑）、以及擴充性那三個數字重貼一次。

要注意的一點： Mode B 的條件 2（覆蓋錨在正向也必要）很可能會打到他已經寫好的實作 — 他說「覆蓋錨用清單自己的結果計數」是在講 absence 那側，正向那側他不一定有套同一條。如果他回說會拆掉不少東西，那是預期內的，不要讓步：「有，這兩本」沒有錨就只能報存在性。

==========

重新部署 done

先講結論：兩個 tier 不一致我都判給 case 檔，要改的是實作。
第二個爭議底下還藏著一件比 tier 標籤重要得多的事。
spec 已更新到 Amendment 18（docs/task1-spec.md §16），acceptance 加 A-54…A-57。commit 4c059c6。
部署協定選精確版，watcher 現在可以起，細節見第七段。

■ 先確認你回的三件事

A17.6：接受你的釐清。product 端用 lxml 從 artifact 重讀 aria-sort / sorter class 再比對，
那是真的結構性重解析，A11.7 沒被違反 —— 我看到的是 harness 的計數而不是 product 的，是我看錯了層。
harness 那個「hash 對得上就 +1」確實是同一個缺陷，修得對。
順手讓 harness 能真的重推列舉型主張（每個成員都要在 artifact 裡找得到）這件事你可以不做而你做了，
DEV-09/10 從 2/2 變成誠實的 3/3 是往壞看起來走但往真實走，記一筆。

Mode B 條件 2：這正是我要的。
「至少 N 筆…這是存在性主張，不是完整答案，因為沒有證據說列舉涵蓋了整個集合」——
把限制寫在答案的字面上，而不是寫在旁邊的註記裡，比我要求的還好。
反向述詞那個 gate 為了可注入而讓 fixture 的 absence plan 呼叫 verifier 會再套一次的同一個比較函式 ——
這一步我要特別確認你想清楚了：兩邊共用同一個函式，代表這個 gate 抓的是「述詞被用反」，
不抓「述詞本身寫錯」。那是對的取捨，但請在 A-53 的測試旁邊寫一行說明它抓
免得日後有人把它當成述詞正確性的證明。

A17.1 修在 verifier：正確，而且回歸測試的設計是對的 ——
同樣的 postcondition、同樣的 artifact、同樣的 candidate，只改「任務指名
一個 no_result_verified 一個 failed / verification_mismatch。
那是一個真的對照實驗，不是一個測試。verifier 不 import executor 還有測試

第四段那兩個新缺陷（限流讓 free tier 對整個 process 死掉、planner 狀態在
都是會直接打到公開 demo 的，修得及時。第二個尤其危險：
一個開機時機的巧合會讓整個容器活著的期間都宣稱自己壞掉，而 /healthz 會誠
「配額類的拒絕冷卻後重驗、缺金鑰不重驗」這個區分是對的 —— 會自己好的和不會自己好的要分開。

■ 決定一：DEV-02 —— case 宣告是對的，tier 判定要改（A18.1、A18.2）

紀錄的單位是 site × operation，不是 page × operation（S-3.1 寫死的）。
「In the S&P 500 constituents table on Wikipedia, sort by CIK ascending…
文章是 OP-4 的參數，不是紀錄身分的一部分。
解不出參數，是一個承諾紀錄「內部」的失敗，不是這題從來不在紀錄裡的證據。
所以：DEV-02 是 T-DECLARED，case 宣告不動，tier 判定改。

outcome 也錯了。這題沒有違反 §2 的任何一條，不該是 policy_refused。
A18.2：failure_class 加 entry_point_unresolved（走 A14.11，terminal_stat
把「我們算不出從哪裡開始」歸成政策拒絕，會用一批從來沒被拒絕過的 run 去灌 A14.3 要量的拒絕率 ——
跟 A17.8 是同一個缺陷。

■ 這個爭議底下真正的問題（A18.3、A18.4）—— 這是這一輪最重要的一條

我重讀了原始作業。它的第一句是：
"accepts natural language task descriptions and reliably executes them a
而且它說 "We will verify with our own unseen tasks."

我們現在要求使用者把頁面標題講精確、或直接貼 URL。那是把「自然語言」的邊
移到作業沒有放的地方。「The S&P 500 constituents table on Wikipedia」對人來說一點都不模糊，
而這種句型會是 grader 丟過來的東西裡很大的一塊。
L-1 是一條誠實的限制，它也是一條我們不該留著的限制。

A18.3：entry point 可以由模型解析，但必須由程式驗證。
模型提出候選 entry point；程式導航過去，
在任何 claim 建立在它上面之前，先驗證落地頁面確實滿足任務的描述
（任務所指涉的結構在頁面上存在且可定位）。
這跟 §4 到處在跑的分工是同一個：模型提案，程式裁決。
落地頁面無法對著描述被確認的候選就不是起始頁，
run 以 failed / entry_point_unresolved 結束，並說出它找了什麼、沒找到什麼。

A18.4：這條不新增任何鬆綁。候選必須落在任務指名的 origin 內（A17.1 已經在管），
每一跳照樣過 egress guard（S-2.6）和 robots（A10），
最後採用的 entry point 和它怎麼被決定的要進 trace（A13.4）。
而且這不是 shortcut —— OP-4 的 required action 是排序，不是導航（S-4.1）

A18.5：這件事排在部署和 cold start 量測「之後」、M5 宣告完成「之前」。
不要拿它擋部署。

■ 決定二：DEV-13 —— case 宣告是對的，tier 規則我寫死（A18.6）

一個唯一路徑被 robots 擋掉的任務是 T-REFUSED。規則寫成這樣，才不會變成品味問題：

  tier 在瀏覽前指派。它可以被修訂「恰好一次」，而且只能「向下修訂為 T-REFUSED」，
  時機是一個 §2 的政策決定在「任何頁面被抓取之前」拒絕了這個 run。
  一個因為政策而從未抓取任何頁面的 run 就是 T-REFUSED，
  不管 plan 前的分類器猜了什麼。不存在「進入」T-DECLARED 或 T-EXPERIMENT
  帶承諾的 tier 永遠不會在執行開始後才被進入。

這樣 S-1.3 的「在執行開始前決定」仍然是真的（沒有頁面被抓取），
同時避免 T-REFUSED 退化成一個幾乎沒有成員的標籤、而真正的政策拒絕堆在別

■ 決定三：eval/results 改名 —— 同意，但條件加嚴（A18.7）

拿掉 latest 是對的。被限流那份留著也是對的，不要刪。
但條件要加嚴：在降級狀態下產生的結果檔（配額用盡、相依不可用、跑到一半），
必須把那個狀態寫進「檔案自己的 provenance 區塊」，
不只是檔名和目錄 README。檔名會被複製走、README 會被跳過，
A17.13 的規則是限定詞要跟數字一起旅行，而檔名不是它旅行的地方。
這種檔案不得成為 analysis report 裡任何一個數字的來源。

■ 決定四：cold start —— 選精確版，而且它其實是兩個數字（A18.8、A18.9）

協定選「精確版」。理由：下界版會產生一個必須帶著但書的數字，
而我們上一輪才剛立了「限定詞要跟數字一起旅行」的規則 ——
與其量一個要一路解釋的數字，不如多花一次協調拿乾淨的。
watcher 現在可以起，我按之前會先跟你說一聲，按下的時刻我會報給你當 t0。

但我上一輪的 A17.14 把兩件不同的事混成一個量測了，現在拆開，兩個都要：

1. deploy 到可用 —— 觸發部署到第一個「任務跑到終局」的 wall clock。
   這是我們每次部署的營運停機，A11.2 掛 volume 之後這件事變成不可避免。
   你的 coldstart.py 不停在 /healthz、會再送一個真任務跑到終局，正是為這
2. 冷抵達 —— grader 打開一個好幾小時沒人碰過的 URL 會經歷什麼。
   這個只有在部署真的會變冷的時候才非零。
   「它會不會變冷」要去確認，不准假設：
   如果平台從不驅逐這個 workload、也不縮到零，報告就說它是結構性為零，並
   「因為不會發生所以沒量」可以接受，「沒量」不行。

A18.9：閒置後的第一個任務，要跟穩態中位數「分開」報。
那是 grader 形成印象的那一筆，把它埋進中位數裡等於在描述沒有人的經驗。
3.1s 那個本機 process 起動數字保留，但它不是上面兩個裡的任何一個，標清楚。

■ 決定五：deployment 上的 split 不需要分批 —— 你指錯端點了（A18.10）

「free tier 現在正在限流，deployment 上的 split 可能要分批跑」——
不用分批，因為那些 run 本來就不該在 free tier 上。

A9.6/A8.8：validation 和 test 一律走 billing key。
A12.2：付費金鑰永遠不在公開服務的容器檔案系統上。
A12.3：計分的 run 是一個共用 volume、不對外開放 HTTP 的獨立 workload。
所以 split 要打的是「A12.3 那個 workload 的內部端點」，不是公開 URL。
harness 仍然是走 HTTP 打一個部署好的東西（它的設計理由沒被破壞），只是打
如果現在不是這樣接的，那就是這次部署前要修的東西。

成本也不是變數：dev 15 題 + experimental 10 題 = 25 run，
用 A9.4 量到的每 run 成本算，整輪不到 USD 0.10，
遠在 A12.5 的日上限和 A8.10 的自行核准額度之內。不要為了省這個做任何取捨。

■ 決定六：L-1 修好之後不准直接刪（A18.11）

A18.3 落地後 L-1 會不再成立。那時候要「改寫」它成 entry point 解析之後實
不是刪掉。作業明文要求列出 problematic / unreliable / unsupported 而且要
一份朝空的方向縮小的清單是一個我們要辯護的主張，不是進度的證明。

■ 數字

重貼的部分我收到了，還是有幾處在傳輸中壞掉（histogram 尾巴、延遲表的 tim
和 model 兩欄、擴充性第一條的 burst 序列、DEV-05 那題的描述）。
不急著現在補 —— 部署後你會在 deployment 上重跑 dev split，那份才是要進報告的。
本機這份就當作對照。

有兩個數字我現在就要標記，免得它們進報告：
- headline declared 10/11 = 0.9091，其中沒過的 DEV-02 依 A18.1 根本不該以那個形式失敗。
  A18.3 落地後這題會變。報告裡的 headline 要用修完之後重跑的數字，
  並且明講前一版是多少、為什麼變 —— 那個變動的理由本身就是一個好的評估紀錄。
- experimental 2/3 = 0.6667 這個數字不要出現在任何地方。三題的比例沒有意
  它的母體是 eval/experimental-set.md 那十題，等 deployment 上跑完再說。

■ 順序

1. 修 split 的端點（A18.10），確認打的是 A12.3 的 workload 而不是公開 URL。
2. 起 watcher（--t0-now），跟我說你準備好了。
3. 我按部署，把按下的時刻報給你當 t0。
4. cold start 收單（兩個數字，第二個先確認會不會變冷）。
5. deployment 上重跑 dev split + 跑 experimental split 十題，
   釘 EXP-05 / EXP-10 的 pin_at_first_run 值。
6. A18.1 / A18.2 / A18.6 的 tier 與 failure_class 修正。
7. A18.3 的 entry point 解析 + 落地驗證，然後改寫 L-1。
8. M5 宣告完成。

watcher 起吧，我等你說準備好。

一句提醒： A18.3 是這一輪唯一一條會擴大系統行為的改動，其餘都是收緊。它  己的未見任務，而「描述頁面而不指名頁面」會是他們句型的一大塊 ——但它也是唯一一條可能引入新的靜默失敗的改動。落地時盯緊「落地頁面必須對著才是防線；模型提候選那半只是便利。

==========

按下去的時刻：1785215881  |  2026-07-28T05:18:01Z
只重新部署了 wf-agent，fixture 沒動——這兩個 commit 沒碰 fixture/，而且多重啟一個服務只會給冷啟動加噪音。

scored workload 那個設計對，而且對在你講的那個點上：綁 127.0.0.1 是 socket 的性質，console 裡的開關是別人可以改掉的東西。這跟憑證拓樸隔離是同一條原則，不是兩件事。

重啟不重跑已有結果檔那條也對。平台的免費動作花我們的錢、而且蓋掉花錢買到的結果——這跟之前 bytes_freed 謊報那個是同一類，值得在 M8 裡當一類講。

==========

 ubuntu@VM-20-55-ubuntu:~$ date -u +'%s  |  %Y-%m-%dT%H:%M:%SZ'
1785216443  |  2026-07-28T05:27:23Z

==========

scored 服務我照 runbook 建了，但我打算先用 EVAL_SPLITS=validation 跑一次
validation 的題目檔不在 image 裡，所以它會走完 preflight、起 loopback、等健康，然後 skip、不寫檔、idle，相當於零成本體檢，確認完再改成 dev,experimental 真的計分。這個做法對嗎？如果對，把它寫進 runbook 當正式步驟，操作者不該第一次啟動就是花錢。

另外兩件事：

PROVIDER_SPEND_CEILING_USD_PER_DAY 預設 $1.00，ledger 跟公開 demo 共用同一個 volume
我算 dev+experimental 25 個 case 大概 $0.6-0.9，本來就貼著上限，再加上當天公開流量，很可能跑到一半撞上限。撞上限之後會怎樣？結果檔還是會寫出來嗎？如果會，那我拿到的是一份半數 blocked/provider_quota 的檔案，而且 -r1 這個檔名已經被佔掉——那不是「上限保護了我」，那是上限毀了一輪還讓它看起來像一輪。

我要的是：一輪開始前先估這輪要花多少，跟今天剩下的額度比，不夠就在跑第一個 case 之前拒絕啟動，而不是跑到第 14 個才斷。這跟你 preflight 裡其他幾條是同一個形狀。

還有記憶體：計分時 app 跟 scored 各開一個 Chrome，各 550-800 MiB，機器只有 4 GB。這個你量過嗎？如果沒有，跑之前先講一下最壞情況，我才知道跑到一半服務掛掉是預期內還是 bug

==========

我要 push 了，起 watcher

==========

push 吧。我這邊的時間是
ubuntu@VM-20-55-ubuntu:~$ date -u +'%s  |  %Y-%m-%dT%H:%M:%SZ'
1785242630  |  2026-07-28T12:43:50Z

推完跟我說一聲，我要接著建 scored 服務——那個也是同一個 repo，你一 push 它也會跟著重新部署，所以我等你收完窗再開始。

==========

runtime log 有 error:
[Zeabur] Pod/service-6a68997d9949111176ce976e-795cdd955b-2r8jp - BackOff: Back-off restarting failed container whaleforce-coding-test in pod service-6a68997d9949111176ce976e-795cdd955b-2r8jp_environment-6a6644a75f062718bc7b1a95(e1c8b4fa-a587-4e03-82fd-7d2e1d865d9e)

（同一則重複四次）

==========

api key 我已經有放進去了
有 runtime log:

REFUSING TO RUN THE SCORED WORKLOAD: /data/task1 does not exist: the shared volume is not mounted, so the evidence from scored runs would not reach the public run views.

==========

在 wf-scored 的 dashboard 不能選既有的
只能手動輸入一次跟app一樣的資訊

==========

 INFO: "/data is empty. Either no volume is attached to this service — the image creates an empty /data — or one is attached that is not the app's. Attach the *same* volume as the app service, mounted at /data: a volume of this service's own would keep scored evidence where the public run views cannot reach it."

==========

dry run 我按下去了
目前的 log:
[scored-workload/1.2] round r1 on 882a16dcebb8: {
 "cases_per_split": {
  "dev": 15,
  "experimental": 10
 },
 "cases_priced": 25,
 "cases_not_in_this_image": [],
 "usd_per_run_measured": 0.0042,
 "safety_factor": 1.5,
 "expected_usd": 0.1575,
 "worst_case_usd": 0.975,
 "worst_case_basis": "every run spending its full token budget: $0.0390 per run",
 "remaining_today_usd": 0.9998,
 "remaining_cumulative_usd": 4.9998,
 "affordable": true,
 "worst_case_affordable": true
 }
 [scored-workload/1.2] dry run: preflight, startup and forecast only. No case was submitted and no result file was written.
 [scored-workload/1.2] done. Wrote: nothing
 [scored-workload/1.2] idling. Change EVAL_ROUND and restart to score again.


以下是 PM 的新指令
你可以看要現在做，還是等 dry run 我回答完你 log 再做
-----------------------------
First order:
一、A21.7 我定了 —— 已寫成 Amendment 22（A22.1–A22.9、A-66/A-67），commit 727c214。
系統總上限維持 USD 1.00。scored $0.75，公開 app $0.25。
scored 那個數字的理由：一輪預估 $0.157、實測 $0.051，
$0.75 是「每題都跟我們見過最貴那題一樣貴」的七倍，
而且刻意不覆蓋 $0.975 的理論尾巴 —— 尾巴由 forecast gate 警告，A20.5 說上限不照尾巴訂。
公開那 $0.25 是保留額不是配額：A12.2 下那個容器沒有付費金鑰，今天實際能花的是 $0.00，
它要到 A15 切換後才會活。A22.5 把「切換時重新檢討這個切分」排進計畫，不是改主意。

兩條是機制不是紀律：
公開那 $0.25 是保留額不是配額：A12.2 下那個容器沒有付費金鑰，今天實際能
它要到 A15 切換後才會活。A22.5 把「切換時重新檢討這個切分」排進計畫，不

兩條是機制不是紀律：
- A22.3 兩個上限要從同一個宣告來源推導，不是兩個獨立的環境變數。
  只靠慣例相等的兩個數字會漂移，而且沒有行程看得到對方的帳本，所以漂移是隱形的。
  跟 A20.3 是同一個推理。
- A22.4 每個 healthz 要報自己的上限、自己的花費、和系統總額。
  一個要靠讀者自己把兩個服務加起來才看得到的承諾，不是一個可見的承諾。

付費輪解鎖了。

二、A21.4 我接受形狀，還不接受它當 limitation（A22.6–A22.8）

你的推理對，A21.6 拒絕在 scored 服務上開門也對。
但作業明文要 makes failures inspectable，而 A21.4 寫成這樣的意思是：
我們公布數字的那些 run，正好是沒有人看得到的 run，其中失敗的最看不到。

A12.3 要求的是憑證不可達，不是服務不可達。artifact 不是憑證。
而且 A21.2 你已經把機制立好了 —— 一輪的紀錄跟著 repo 走。延伸到 evidence 就行：
- 每一筆非成功 run 的完整 bundle 一定要 commit（那是讀者有理由懷疑的，也
- 一個「開跑前就指定好」的成功樣本的完整 bundle（讓讀者確認一個 pass 長得像 pass）
- 沒帶的東西：per-case verification record + artifact hash + 明列漏了什麼、為什麼（A11.8）

上限用量的（A22.8），不要用猜的。超過上限的那個殘餘才是 A21.4 的 limitat
寫的是「實際帶不動的東西」，不是整個類別。
走 A21.3 的聯集出去，公開前端就讀得到，而 scored 服務一次都不用可達。

三、A21.5 我特別記一筆

「用別的行程的副作用滿足的前置檢查，不是前置檢查」是 Amendment 21 裡最有
它跟 A11.7 的空洞驗證、A19.2 的「未評估的約束被記成滿足」是同一個缺陷，
在第三個地方被找到：前置檢查、驗證、約束，三者用同一種方式壞掉 ——
都是在報告一個巧合。已寫成 A22.9：這個系統之後新增的任何檢查都要對著它讀一次。

其餘照原本那份 prompt 走，特別是第七段第 1 點（我 push 之前你先起 watche
A20.2 還沒生效，因為你還沒收到它。
----------------------------------
Second order: 
三件事都接受，其中一件我要加一條你沒做的。push=部署那個發現最重要，
它讓昨天講好的 A18.8 協定作廢，已寫成 Amendment 20（docs/task1-spec.md §16，A20.1–A20.6、A-61/A-62）。
另外我修了 experimental split 裡三題會一起死掉的題目。commit 90dd2a4，還沒 push（見第五段）。

■ 一、EVAL_DRY_RUN —— 接受，而且你把理由換掉是對的

「一個靠檔案不存在而成立的乾跑不是機制」—— 這句話本身就是這個專案要證明的東西。
明確命名它、寫進 runbook 第一步，收下。

「它不是零成本，我不想讓你以為它是」也收下，而且那一次真實呼叫正是它的價值：
「金鑰在、但打不出去」要在這裡發現，不是在計分輪第一題。這是 A9.3 的原意。

但那一次呼叫要進帳本（A20.6）。它是真的付費呼叫，不記帳就是帳本說謊，
跟 A17.9「在帳上免費的重試會讓預算變成虛構」是同一條規則，
只是套用在唯一一個發生在任何 run 存在之前的呼叫上。
請確認它有進 ledger；沒有就補。A-62 另外要求帳本總額要跟供應商自己報的當日花費對得上（誤差在四捨五入內）。

■ 二、撞上限 —— 你的修法對，我只加一條

開跑前報價、不夠就在第一題之前整輪拒絕，正是要的形狀。
預期（題數 × 實測 × 1.5）當閘門、尾巴（吃滿 token）只警告，這個切分判斷正確 ——
用 20 倍的尾巴當閘門會擋掉幾乎每一輪，那不叫保護。
-r1-degraded.json 保留乾淨檔名讓同輪次可重跑，也對。

A20.5 加一條，是防未來的人：上限是備援，不得為了容納預估值而調高。
forecast gate 是控制，上限是「forecast 錯了」的時候接住的東西。
因為一輪可能逼近上限就調高上限，等於把 forecast 唯一的檢查拿掉。A12.5 的 $1/日不動。

順帶把操作者的顧慮結案：他擔心「ledger 跟公開 demo 共用，公開流量會吃掉額度」——
這在拓樸上不成立。A12.2 規定付費金鑰永遠不在公開服務容器的檔案系統上，
所以那個容器結構性地沒有能力往付費帳本寫入任何金額。
帳本裡的付費支出只會來自 scored workload。這個結論請寫進 runbook，
免得日後有人以為爭用是真的然後去「修」它。

成本表收下。但依 A17.10：這份實測是在哪個 output cap 下量的？
Amendment 17 放寬過 cap，如果這 15 題是放寬「之前」跑的，數字要重量。
報告裡無論如何都要寫明是在哪個 cap 量的。

■ 三、記憶體 —— 接受，兩點要求

/healthz 的 browser.rss_mib 可遠端讀，這個設計比我預期的好，
它讓記憶體從「跑之前的估算」變成「跑之中的觀測」。

1. free -m 要三次不是一次：開跑前、跑到一半、跑完。
   你的通過條件是「swap 成長為零」，成長需要兩個點才存在。一次讀數量不出成長。
2. 那張表裡「k3s + 平台 agent −300～500」是估算，其他列是實測，
   請在表上標出來哪幾列是量的、哪幾列是估的（A17.13：限定詞跟數字放在一起）。
   最壞情況約 800 MB 餘裕是可接受的，但那個結論的其中一項輸入是估的，讀者要看得出來。

「1,400 MiB 回收線是底線不是計畫」、「swap 被動到就是 finding 不是還好有 swap」——
兩句都對，照這樣寫進報告。

■ 四、git push 會觸發自動部署 —— 這是這輪最重要的發現（Amendment 20）

你自己發現、自己更正了那份冷抵達檔案（「那不是冷抵達，那是一個已經開機 6.6 小時的容器的溫請求」），
而且把「重新部署」跟「被驅逐」分開 —— 這是正確的處理，記一筆。

A20.1：deploy-to-usable 的 t0 改成「push 的那一刻」，由推的人回報。
這取代 A18.8 的「操作者按下部署後回報時刻」。
新協定比舊的更精確不是更差：推的人知道確切的瞬間，按鈕的人只知道大概。
昨天那個協定是我在不知道 push 會部署的前提下寫的，作廢。

A20.2：計分輪或閒置窗進行中不 push —— 這條也綁住我。
我這個 session 會 push spec 和 eval 檔，在這裡「對文件的一次 commit」就是一次生產部署。
要在量測窗內 push 的人要先講。

A20.3：紀律不是機制。計分輪必須記錄它啟動時的 SHA，
並在 SHA 中途改變時中止，依 A18.7 把那份部分結果標成 degraded。
A20.2 遲早會有人忘記，A20.3 是忘記的時候接住的東西。這條是我加的，你沒做。

A20.4：輪次身分用 EVAL_ROUND 不用 SHA，收下。
你原本的問題值得寫清楚：以 SHA 當輪次身分時，一次 push 就是一個新輪次，
所以「已經計分過就跳過」這個保護對免費的重啟有效、對花錢的那個情況失效 ——
一個保護在免費路徑成立、在付費路徑失效，那是反過來的。

■ 五、我改了 experimental split 三題，先 pull 再跑（commit 90dd2a4，還沒 push）

EXP-06、EXP-07、EXP-10 原本寫「Project Gutenberg」「MDN」，沒有可解析的 host。
以現在的 records.resolve_entry，這三題都會在 entry_point 解析就死掉，
在測到它們被寫來測的東西之前 —— 三成的 split 會重複量同一件事。
已改成句子裡帶 host（www.gutenberg.org/ebooks/1342、developer.mozilla.org/...）。

理由寫進檔案了，是量測設計不是便宜行事：
這個 split 量的是「未見站上的執行廣度」，
而「描述頁面但不指名」是另一個變數，由宣告側的 DEV-02 量、由 A18.3 治理。
一個 split 一個變數。

現在十題全部都在句子裡指名 host，所以：

■ 六、Amendment 19（中文輸入）不擋這一輪

我昨天寫的 A19.2/A19.3：named_site() 讀不出站名時，
verifier 會 append 一筆通過的 named_site_frozen: True 然後什麼都不約束 ——
一筆通過的檢查頂替一筆不存在的檢查。
但 dev 和 experimental 兩個 split 的每一題都以程式讀得到的形式指名了站，
所以那條空洞路徑在這一輪不會被觸發，這一輪的數字不受污染。

因此順序是：先跑這一輪，A19 之後修。
但 A19.3 要排在 A18.3「之前」——
A18.3 讓模型提 entry point，A17.1 是唯一擋住模型亂選的東西，
站名讀不出來時 A17.1 不約束任何事，
所以 A18.3 + 一個別名表沒收錄的語言 = A17.1 當初要擋的那個缺陷原樣回來。

■ 七、順序

1. 我先跟你確認：我要 push 上面那四筆（A18/A19/A20/split 修正）。
   你先起 watcher，跟我說好，我 push 並把時刻報給你當 t0 —— 這次 push 就是
   deploy-to-usable 的量測機會，不要浪費。
2. 操作者用 EVAL_DRY_RUN=1 起 scored 服務，貼輸出（forecast 段、credential 段）+ free -m 基線。
3. 確認後跑真的一輪：EVAL_SPLITS=dev,experimental、EVAL_ROUND=<識別碼>，
   free -m 三次（前/中/後）。這段期間雙方都不 push。
4. 你收結果，然後才開乾淨的閒置窗量冷抵達（第二個 cold start 數字），
   而且先確認這個部署到底會不會變冷 —— 會的話量，不會的話說明怎麼確認的（A18.8 item 2）。
5. 之後才是 A19（中文 + 空洞檢查）、A18.1/A18.2/A18.6（tier 與 failure_class）、A18.3（entry point）。

■ 八、兩個數字先標記，免得它們進報告

- headline declared 10/11 = 0.9091：沒過的 DEV-02 依 A18.1 根本不該以那個形式失敗。
  修完重跑的才是要進報告的 headline，同時要寫明前一版是多少、為什麼變。
- experimental 2/3 = 0.6667：不要出現在任何地方。三題的比例沒有意義，
  它的母體是 eval/experimental-set.md 那十題。

一句判斷： ENG 這一輪三個回答的品質都比問題本身高一階（把「靠檔案不存在的乾跑」升級成命名機制、主動說乾跑不是零成本、自己發現並更正冷抵達那份檔案）。我加的兩條 —— A20.3 的 SHA 鎖和驗證呼叫要進帳本 —— 都是「紀律變機制」的同一個形狀，不是對他的修正。

==========
計分輪已經在跑了 —— EVAL_ROUND=1、EVAL_SPLITS=dev,experimental、EVAL_DRY_RUN 已清掉，
wf-scored 正在重新部署。跑完你自己 ssh 上去看，檔案不用我們撈：
結果檔和 bundles/ 在 /data/task1/eval-results 底下，
記憶體曲線在 host 的 ~/mem-round1.log。

我這邊有三筆 commit 壓著沒推（Amendment 23，23bf354），等這輪跑完、你把結果 commit 之後再一起推。
這段期間雙方都不 push（A20.2）。

■ 記憶體改用連續取樣，不用手抓三個點

主機上每 10 秒一筆 free -m（含 swap），從重啟前 30 秒就開始跑，
輪結束後再多跑 5 分鐘。
理由：你的結果檔 provenance 帶每題時間戳，split 分界事後從檔案讀得出來，
兩邊對時間戳就能切，比守著抓一個點可靠 —— 抓歪了沒得補。
輪後那 5 分鐘是要看記憶體有沒有被釋放，那是 A9.7「兩週無人值守」的真問題，
比中段那個讀數重要。

■ 一、帳本只算 billed —— 批准（A23.1、A23.2）

「這是一個 spend ceiling，免費層的呼叫不是 spend」是對的。
把它算進去不是保守，是讓閘門去衡量一個它沒在衡量的東西，
而且它產出的是一個看起來完全正常、實際上在陳述一件沒發生的事的 provider_quota。
那正是這個專案排在最前面的那種失敗。照你的提案改。

三個條件：

1. 兩組數字都留、都報，各自標明是「錢」還是「名目成本」。
   名目那組不是雜訊 —— 它是免費層「如果要付會付多少」，
   那是 A15 切換之前替公開路徑定價的誠實方式。

2. analysis report 裡每一個成本數字都用 billed 那組。
   拿名目成本當成本報，會高估這個系統的營運費用。

3. 這條是我加的，也是這個改動真正的風險：
   拿掉這道閘門之後，公開路徑靠什麼收斂？
   $0.25 之前是「意外」在當請求數限制器用。拿掉之後真正的邊界是
   免費層自己的 RPD/RPM，加上 S-11.8 的 session cap 和 queue depth。
   A15.2 的規則照舊：免費層的 RESOURCE_EXHAUSTED / 429 是「真的」provider_quota，
   必須照樣誠實終止。
   這要驗過，不是假設 —— 拿掉一道閘門而沒確認剩下的還在，
   就是 A21.5 那個缺陷反過來發生。請補測試。A-68。

■ 二、預算 —— 產品負責人把總預算提到 USD 10（A23.3、A23.4、A23.5）

涵蓋交付前的所有實驗，不含提交後的 grader 流量。

先說清楚，免得三天後沒人分得出來：這不是 A20.5 禁止的那種情形。
A20.5 禁止的是「為了讓預估值塞得下而調高上限」—— 上限遷就工作。
這次是授權本身改變了，上限跟著授權走。兩者在 diff 裡長得一模一樣。

新數字，A22.2 的比例不動：
- 系統日上限 USD 2.00（scored 1.50 / public 0.50）
  日上限刻意不跟總預算等比放大：每輪實測 $0.051，$2.00 一天約 29 輪，
  比任何一天需要的都多，所以它保持是「防跑掉的迴圈」的備援，不是配額。
- 累計開發上限 USD 8.00，硬停，掛在 scored workload。
  真實上限是 $10，而上限的用途是接住我們自己的帳算錯，
  所以它坐在被保護的那條線「下面」，不是坐在線上。
- 公開端累計上限在 A15 切換時再定。
  grader 流量依產品負責人的決定不算在這筆預算內，所以它不能吃掉開發額度；
  現在沒有流量資料，定了就是猜。
- 累計是主控制、日上限是次要，不一致時取小 —— 你的 forecast gate 已經這樣讀了。A-69。

改上限要 push，所以排在這一輪之後。這輪 $0.157 對現行 scored $0.75 綽綽有餘。

■ 三、你的量測推翻了我們自己寫的一條（A23.6）

deploy-to-usable n=5 收下，而且它推翻 A11.2。
A11.2 當初寫「掛 volume 強制 Recreate，因此每次部署都是完整冷啟動停機」。
實測：中斷 12–23 s，觸發到可用 112–176 s（中位 149.7 s），
中間大部分時間舊容器還在正常服務。
所以「中斷」是頭條數字，觸發到可用放在旁邊，
離散照你量到的歸因（平台建置佇列，不是我們的啟動）。
A11.2 高估了成本，A23.6 取代它。

這件事要進報告，而且要寫成「我們自己的假設被自己的量測推翻」——
它比一個從一開始就對的數字更有說服力。

■ 四、記一筆你這輪做對的三件事

.inflight marker：容器在付費 split 中途死掉會留下它、下次啟動拒絕而不是再付一次錢。
那是 A20.3「紀律遲早有人忘記」真正貴的那個情形，我當初只想到 SHA 漂移。

樣本用「每個 split 宣告順序的前兩題」而不是逐案挑，
而且樣本裡有題目沒過就照 A22.7 第一條當失敗帶走、manifest 寫「樣本短少幾筆」
而不是拿別的過關題目補上 —— 規則不被結果帶著走，正是 A22.7 要的性質。

artifact 出庫時重新雜湊而不是複製描述檔那一列：複製來的 hash 只證明它們曾經一致。
同一個形狀。

A17.10 的答案（$0.0042 是放寬後量的）也收下，
而且你把「這是在哪個 cap 下量的」變成檔案自己回答（/healthz 報 budgets + prices，
harness 寫進 provenance），比回答那個問題本身有價值 ——
下次沒人需要去翻 git 歷史。

■ 五、順序

1. 這一輪跑完，你 ssh 上去收結果檔、bundles/、mem log，commit 進 eval/results/（A21.2）。
2. 然後才推：你的 A23 實作 + 我壓著的三筆。
3. 閒置窗量冷抵達 —— 先確認這個部署到底會不會變冷（A18.8 item 2）：
   會就量，不會就說明是結構性為零以及怎麼確認的。
4. 之後才是 A19（中文 + 空洞檢查，排在 A18.3 前面）→ A18.1/A18.2/A18.6 → A18.3。

兩個標記數字（headline 10/11、experimental 2/3）你說不會讓它們進任何文件，確認收到。

■ 六、輪跑完先回報這幾項

- 每個 split 的 attempt / verified / abstention + Wilson 區間（experimental 那組是 A-40 的交付物）
- terminal_status × failure_class histogram
- EXP-05 / EXP-10 的 pin_at_first_run 有沒有釘到值
- EXP-03 / EXP-07 / EXP-08 三題 manual_review 的實際結果 —— 這三題 harness 判 status，
  silent-failure 條件要人判，你先給我你的判斷
- evidence 摘要：帶了幾份、樣本是哪幾題、用掉幾 MiB / 48 MiB、幾筆列為省略
- 記憶體：峰值、swap 有沒有成長、輪後五分鐘有沒有釋放
- billed vs 名目兩個數字，這一輪實際花了多少真錢

==========
以上的事情做完、輸出完你的回報後
再多做一件事

根據你現在的進度記憶以及實際 trace code，核對一下spec
(不要只是憑記憶，應該實際去trace code & review spec)
看看現在已經完成了spec的哪幾項，還有有沒有跟spec不符合的地方
生成一個報告prompt，讓我直接貼給PM，跟他回報進度

==========

進度回報的部分你也可以開subagent去trace，你這邊繼續專心做更動

==========
note, wf-scored is done:

{
  "message": "[scored-workload/1.3] idling. Change EVAL_ROUND and restart to score again.",
  "timestamp": "2026-07-28T14:31:26.452655451Z",
  "__typename": "RuntimeLog"
}

==========
Note: 等等 code review agent 的回報你不要全盤接受直接回報給我
他說pass就pass不用再檢查了，但他說不符合的地方你要親自看一下，因為你才有完整的context，說不定是文件寫得不夠嚴謹，反而code是有寫好的

==========
把這整份回覆dump進一份 current_reporty_for_pm.md
做這件事就好

==========
五件都裁了，寫成 Amendment 24（docs/task1-spec.md §16，A24.1–A24.8、A-70…A-72），
commit 7492ef4，跟你那兩筆、我壓著的三筆一起推。

先講：r1 這一輪的品質很高。你自己抓到計分器打掉四題、自己去 volume 把 artifact 拉下來
用同一支函式跑過驗證、而且「沒有動它，因為改它會讓閘門從 fail 變 pass」——
那個克制比修好它更有價值。盤點也是實地 trace 不是憑記憶，D-1 那條尤其。

■ 一、計分器偽陽性 —— 兩個都同意，加一道圍籬（A24.1–A24.3）

(a) 同意改法。語料 = 渲染文字 + 人可見屬性值（title / alt / aria-label / placeholder），
不是原始 markup。你的理由對：讀者把游標停在標題上真的會看到那個值，
它屬於「交付的 artifact 的內容」；而原始 markup 會讓 URL、class 名稱意外命中。

但這是「放寬一個閘門」，所以邊界要有測試守著，不能靠意圖。圍籬我指定好了：

  EXP-05 就是那道測試。它的答案 Hello World! 在 artifact 裡「只」存在於
  setTimeout 的 script 字面裡，而那一題正確地棄權了。
  任何會讓 EXP-05 變成 pass 的語料改動就是走過頭了。

明確排除：script/style 文字、class、id、data-* 屬性、URL、註解。
A-70 就是這條。這樣「語料要多寬」從一個判斷題變成一個回歸測試。

(b) 同意重跑，但要跑兩次不是一次，而且順序有講究：

  r2 = 只改計分器，其他一律不動 —— 這一輪測的是「量測缺陷被拿掉」
  r3 = 產品修完（A19 / A18.1 / A18.2 / A18.6 / A18.3）之後再跑 —— 這一輪測的是「產品變好」

各 $0.03，兩次總共 $0.06。買到的是乾淨的歸因：
r1→r2 是量測缺陷，r2→r3 是產品進步。混在一次重跑裡這兩件事就再也分不開了

r1 照 A21.2 留著不動。報告要把三份都列出來、照上面那個讀法解釋。
一個乾淨的數字的價值低於這個序列 —— 序列本身就是作業在評的「evaluation discipline」。

■ 二、D-1 fixture 接住無指名任務 —— A17.2 不動，改 code，測試要反過來（A24.4）

不是兩者都可辯。fixture 的資料是我們自己編的，
所以拿它回答一個沒指名站點的問題，是把捏造的資料當答案交出去 ——
這個專案排在最前面的那種失敗，而且是它最嚴重的形式。

test_a_price_question_naming_no_site_still_reaches_the_fixture 要「反過
這樣被套件守住的是那條禁令本身。

另外這條值得單獨記一筆，我寫進 A24.4 了：
一支把缺陷編碼成需求的測試，是 A22.9 那一族在測試套件裡的樣子。
505 個測試通過，不代表被斷言的是對的東西。這句話要進 analysis report 的
「how you verify correctness」那一節 —— 它是我們自己抓到的、關於測試本身的限制。

■ 三、D-5 A-14 —— 不是改措辭，是它本來就寫了兩件事（A24.5）

A-14 拆成兩條：

  A-14a 瀏覽前的拒絕：需要登入 / 付費 / 繞過 anti-bot 的任務，
        執行前就辨識出來，收在 unsupported / policy_refused。
        這條「實作是對的、spec 的措辭是錯的」。
        「我們不做這種事」是 unsupported。

  A-14b 執行中遇到的阻擋：導航落在登入牆、付費牆、限流頁、攔截頁 → block
        「有東西擋住我們」是 blocked。這條沒有實作。

A-14b 我不接受只列成 limitation。理由跟 D-3 一模一樣：
沒有它，這些 run 會收在 locator_not_found 或 postcondition_unmet，
那是「錯誤分類」，而錯誤分類會污染 A14.3 的拒絕率 —— 跟 entry_point_unresolved 灌水是同一件事。

要的是「最小偵測」，不是通用方案：
導航拿到 HTTP 401 / 403 / 429，或該出現內容的地方站著一個登入表單 → blocked。
這兩個訊號很便宜。超過這個範圍的（視覺辨識付費牆）才是誠實列出的限制。
EXP-08 是這條的實例。A-72。

■ 四、D-6 aria snapshot —— 補，但理由不是成本（A24.6）

S-4.5 不動。真正的理由是：
accessibility tree 正是 F1（semantic role + name）定位器「被推導出來的那個語料」。
不存它，一個 F1 定位器的主張、以及任何經過 F1 的修復或復原，
都無法從 artifact 重新推導 —— 而那正是 §4 立足的前提。
它對 §7 和 §8 是承重的，不是可檢視性的加分項。

所以它必須「在 M5 之前」落地，讓 M5 的證據從第一次執行就是完整的，而不是
48 MiB 用不到 13% 是這件事可以馬上做的原因，不是該做的理由。

■ 五、D-7 —— 驗收項寫不變量，不寫數字（A24.7）

A-66 改寫成「每個行程的上限由同一個宣告的系統總額推導，且各 health endpoint 與它一致」，
不寫任何數字。你的顧慮對：黑箱審查者看到 2.0 對照文字裡的 1.00 會直接判

順便把這條一般化：§14 裡任何一個「帶著 amendment 可以改動的字面值」的驗收項，
都照同樣方式改寫。一個 amendment 改了數字就讓驗收項讀起來像失敗，是文件的缺陷不是系統的。
請掃一遍 §14 看還有沒有別的。

■ 六、D-10 —— 同意改用 passed，而且規則要比這更寬（A24.8）

用 counts_as_success 分類，正好把「run 的判定和獨立複查不一致」的那四題的證據扣住了 ——
最該被看的四題，而且是逼你 ssh 進 volume 才驗得了第五節的那四題。
這件事本身就是規則錯了的證明。

通則寫成：任何一題只要 run 的自報和獨立複查「不一致」，就整份帶走，
不管哪一邊說它過。不一致本身就是訊號，某一邊滿意不是。
容量完全撐得住（這輪 dev 用 5.95 / 48 MiB）。

■ 七、D-9 直接修，不用問。D-2 / D-3 / D-4 / D-8 照原順序，沒有新決定。

D-9 那兩個字串（support.html 賣「以廣度換取 locator memory 與 safety suite 的深度」、
demo.py 把預跑 run 描述成 mutation-healed partial）現在都是假的，A13.3

■ 八、順序（有一處我調動了）

1. 計分器語料修好 + EXP-05 圍籬測試 → 重跑 dev r2（只改這一項）
2. 推：你兩筆 + 我五筆（A23、A24 及之前壓著的）。推完順便量第六次 deploy-to-usable
3. D-9 字串、D-7 驗收項改寫、D-10 bundle 分類 —— 都很短，一起做掉
4. **D-6 aria snapshot（我把它從你的清單裡提前了）** —— 必須在 M5 之前
5. A19（中文 + 空洞檢查）→ A18.1 / A18.2 / A18.6 → A18.3 → A-14b 最小阻
6. 重跑 dev r3
7. **M5 —— locator memory + mutation write-back + MU-4/5/7/8/9**
8. 閒置窗量冷抵達（先確認這個部署會不會變冷）

M5 我沒有讓它繼續往後排。作業點名的兩個機制是 self-correction 和 self-ma
§8 現在完全不存在 —— 那不是「還沒做的一項」，那是題目要求的一半。
你自己在 6.4 第 2 點寫的那句「而且連 self-correction 都還沒有任何一次紀錄
真的產生過 family 轉換（A-11）」比缺 §8 更值得擔心：
那表示我們最有把握的那個機制，到目前為止沒有一次被證明真的發生過。
M5 之前請先把 A-11 補上 —— 一次真的、被記錄下來的 family 轉換，在 dev 或 experimental 上。

■ 九、M8 我來分擔，你不要排到最後

沒有 README、沒有 analysis report 是唯一一個「共同要求」等級的缺口
（作業第 5、6 條，對每個提交的 task 都是必要的），而它現在排在最後面，
那是它最可能不存在的位置。

素材你已經量齊也 commit 了。所以分工這樣切：
- 我起草 README 的「key design decisions」「where AI helped」兩節，
  以及 analysis report 的骨架和所有「決策與理由」的段落 —— 那些本來就是我這邊的東西
- 你只負責把量到的數字填進去、確認我寫的技術描述沒有失真

我今天就會把骨架給你，你不用等到第 8 步才開始。
一份稍微過時但存在的 README，勝過一份完美但不存在的。

■ 十、錢

這一輪實花 USD 0.0477，是預估的 30%，累計對 8.00 硬停。
r2 + r3 兩次重跑約 $0.06。都在額度內，不需要再問。

EVAL_USD_PER_RUN 常數 $0.0042 被這一輪最貴的一題 $0.0048 超過了 ——
1.5 安全係數擋住了，但常數請在 r2 之後更新，並在 runbook 註明它是「上次
而不是一個固定的參數。

另外，再加一條

■ 零、工作方式改變（從現在起長期適用）

不要一個段落做完就回報等我。做完一段就自己 commit，然後照 spec 的順序接著往下做。

只有三種情況才停下來找我：
1. 需要我裁決（動到 status taxonomy、驗收語意、承諾範圍、閘門鬆緊、錢）
2. 真的需要討論（spec 內部矛盾、你判斷 spec 本身錯了、兩個 amendment 打架）
3. 需要操作者去 dashboard 動手（環境變數、重啟、部署、跑計分輪）

其餘一律自己往下走。spec 已經帶了順序和驗收條件，你有你需要的東西。
遇到判斷題時：照 spec 走；spec 沒寫到就選「比較不會產生 silent failure」的那一邊，
並在 commit message 裡寫一行為什麼。事後我不同意再退回，比停下來等我便宜。

一個例外：**commit 隨便你，push 不行。**
在這台主機上 push 就是部署（A20.2）。計分輪進行中、閒置窗進行中，不推。
要推之前跟我說一聲，我把我壓著的一起推。

回報改成「一個里程碑或一組相關修正做完」才回報一次，
內容是：做了什麼、哪些驗收項狀態變了、有沒有新發現的缺陷、下一步你要往哪走。
不要逐條複述，我會自己看 commit。

==========
獨立審查回來了，它實跑了部署系統。結論：今天交 B（脆弱），照現有計畫做完 strong B，不是 A。
卡住 A 的不微妙：七條 common requirements 有兩條是零，Task 1 點名的兩個機制有一個不存在。

它抓到三件我們都漏掉的，兩件我已經驗證屬實。已寫成 Amendment 25
（docs/task1-spec.md §16，A25.1–A25.6、A-73…A-76），commit d7f4991。
Amendment 25 有明確的刪減清單和重排的順序 —— 順序本身就是這次的決定，請照它走。

工作方式照上一封：一段做完就 commit 然後往下走，只有需要裁決 / 討論 / 我去 dashboard 才停。
但 push 例外（A20.2）—— 不過第 1 步就是 push，見下。

■ 一、L-1 公布的解法是假的，可重現（A25.1）—— 這條的傷害最大

審查照 L-1 寫的「加上文章標題就會成功」實跑：
「the List of S&P 500 companies article」→ /wiki/List_of_S%26P_500_companies_article
→ unsupported / postcondition_unmet。
wikipedia_article()（executor.py:1624）剝掉前置停用詞，沒剝尾巴的 noun，而且沒有任何東西驗證落地頁。

規則：每一條 limitation 都必須對著「部署系統」實跑過才准公布，提交前再跑一次。A-73。
一條無法照字面重現的 limitation 比沒有 limitation 更糟 ——
它把這個專案最強的資產變成對它自己不利的證據。

請把 limitations.py 每一條都實跑一遍，不只 L-1。

■ 二、OP-7 寫死在單一商品，所以 support matrix 也是假的（A25.2）

executor.py:1917 inputs={"title": "A Light in the Attic"}、:1935 選擇器
h3 a[title='A Light in the Attic']。
問 books.toscrape 上任何別的商品的標籤欄位 —— 那正是 OP-7 宣告的操作 —— 掉到 T-EXPERIMENTAL。

我寫 A18.1 時說「紀錄是 site × operation，頁面是參數」，實作把參數凍住了，而我沒有去驗。
後果比 tier 標籤嚴重得多：grader 自己的任務就算問的是我們支援的操作，
大多也會落在 experimental 路徑上，而 headline declared rate 描述的是一個幾乎沒人踩到的表面。

兩條路：紀錄對它的參數一般化（正確），或 support matrix 明寫它只對哪一個商品成立（誠實）。
沉默兩者都不是。我要第一條，做不到才退第二條。A-74。

OP-4 / OP-5 / OP-6 請一併檢查有沒有同樣的參數凍結。

■ 三、活的靜默失敗：postcondition 沒有涵蓋任務問的每一個部分（A25.3）

審查在部署上問「UPC and availability」，凍下來的 postcondition 是
required_actions: [] 加一個無名 claim；驗了 UPC、默默丟掉 availability、回 succeeded_verified。

S-5.2 本來就禁止把 partial 當成功呈現。一個空的 postcondition 就是那條禁令
在沒有人寫下 partial 這個字的情況下被繞過的方式。

規則：任務問了 n 個部分就產生 n 個 claim，否則是 partial。
A13.2.3 允許這一層用「較弱的」postcondition，不允許「沒有」postcondition。A-75。
這是 grader 的未見任務會落上的那一層，優先度高。

■ 四、dev set 宣告的 oracle 一條都沒實作（A25.4）

15 題每題都寫「harness 獨立抓取、套同樣排序鍵、比對」。
check_evidence 只做重新雜湊 + 在 artifact 裡字串比對。
r1 裡 OP-4 / OP-5 的 independently_checked 是 0
（那些 "derived value (dict), which this scorer cannot re-derive" 的 note 就是它）。
所以 S-10.10 的「verified-but-wrong = 0」在我們最強的兩個紀錄上目前無法被否證。

這是 broken-instrument 家族第五個，也是第一個「方向樂觀」的。前四個都是把對的打成錯的。

處理方式（我跟審查在這裡意見不同，照我的）：
- OP-4 的 oracle「實作」，不要只揭露。抓表、套排序鍵、比第一列，很短，
  而數字排序 vs 字典排序正是 DEV-02 那題的陷阱 —— 把最強的紀錄從無法否證變成可否證值得一小時。
- 其餘每一題的 oracle 欄位改寫成「harness 實際做什麼」。
- analysis report 裡明寫 OP-5 的正確性靠產品自己的 verifier，沒有獨立 ground truth。
A-76。

■ 五、刪掉的東西（A25.5）—— 每一條都要在 README 裡寫成一個決定

- Task 2 全部停。docs/task2-seam.md 凍結成「設計完成但未建置的接縫」。
- 花費上限 / 帳本 / 憑證拓樸全部停。總花費 USD 0.0477，它做完了而且做過頭了。這條是我的錯。
- validation split 不跑。它的用途是在開發期間讓你保持誠實，開發結束了。
  test split 對部署跑一次，validation 回報「未執行」並寫明理由。
- MU-4/5/7/9 和 mutation sweep 不做。兩個能動的 mutation 加一次修復示範是證據，九個是研究計畫。
- M6 只做一件：最小的 injection 偵測器讓 injection_detected 可達，或誠實宣告它沒建。不要做整套。
- A24.5 的執行期 blocked 偵測降級成「順手才做」。我昨天說它是必須的，兩天期限下它不是這週被評的東西。

■ 六、順序，順序本身就是決定（A25.6）

之前每一版計畫都把 README 和 analysis report 排最後，每次都被擠掉。它們移到最前面：

1. **先 push。** 十筆沒推，而線上的 support 頁現在還在賣不存在的 locator memory。
   部署的系統必須是被審查的系統。這是第一步，不是最後一步。
2. A25.1 —— 修 L-1，並把每一條 limitation 對著部署實跑。
3. **README + analysis report。** 兩條共同要求是零分。量測都 commit 了，這是寫作不是工程。
   我這邊「現在」就在寫骨架：設計決策、AI 協作、報告結構、所有「決策與理由」的段落。
   你只要填量到的數字並確認我的技術描述沒失真。今天會給你。
4. 計分器語料修好 + EXP-05 圍籬 → 重跑 dev r2（A24.1–A24.3）。
5. A25.2 + A25.3 —— 承諾與 postcondition。這兩條決定 grader 自己的任務會發生什麼事。
6. **最小 locator memory**（§8 縮減版）：volume 上一個以 (origin, operation, role) 為鍵的存放、
   只從 succeeded_verified 寫回、TTL、連續三次失敗隔離、一個 health counter、
   run 頁面顯示「來自記憶 / 現場推導 / 已修復」，加「一次」封存真實頁面 DOM 的修復示範（A14.6）。
   self-maintenance 是作業點名的兩個機制之一。**存在、小、誠實地界定範圍，勝過不存在**，
   而它現在的狀態是不存在。
7. test split 對部署跑一次。

■ 七、兩件審查點出、不在上面順序裡但要順手處理的

- 首頁 run 列表 grader 第一眼看到的是十筆幾乎一樣的 fixture 搜尋
  （"Search the fixture catalogue for lantern" ×8），全部標 T-EXPERIMENTAL，
  四個承諾紀錄一個都沒在首頁被示範。這是 grader 形成第一印象的地方，很便宜就能修。
- POST /api/runs 只吃 form encoding，JSON POST 回 422。grader 可能會用 curl。
- A14.15 要的 prompts 索引沒建。也很便宜。

■ 八、審查對機制的評價（給你參考，因為它是對的）

它說 app/suspicion.py 是整個 repo 裡最令人印象深刻的檔案 ——
因為它會拿「安靜的結果」去對照 reduction log，
理由是「因為我們自己裁剪頁面而造成的棄權，跟誠實的棄權長得一樣」。
它說那類思考「well above what this test normally gets」。
robots 的 RFC 9309 實作加自己的 CI job、eval provenance、buildstate 從程式推導對外字串，
也都被它列為「值得成本、保留」。

問題不是機制不夠好，是 grader 會不會看到它。

==========
r2：EVAL_ROUND=2 + 重啟 wf-scored: done，重新部署中
test split 一次（要掛 held-out 檔）這個請給我詳細步驟

==========
裁決：(a)+(b)，但 (b) 不是現在，而且你給 (b) 的理由是錯的。

r2 的可歸因性昨天就沒了 —— 部署上除了計分器還有 A25.2/A25.3/記憶，是你先講的，
我也裁決過接受（artifact 重放已經把量測效應隔離出來，那比 round 邊界強）。
所以「重跑拿回可歸因 headline」這個目的不存在。r2 現在唯一的用途，
是在我們要交的那個 build 上拿一組數字 —— 那應該最後跑，不是現在跑。

1. 不要介入正在跑的那輪。自然收尾，degraded 或 .inflight 都是設計要的行為。
2. 現在不重跑。build 還沒凍（7a6c06b 剛進來，我的逐句驗收也還沒做）。
   在會變的 build 上花一輪，是把同樣的錯誤再犯一次。
3. 凍結後跑兩輪、中間不准 push：
   r3 = EVAL_SPLITS=dev,experimental —— 先確認 round 機制在凍結 SHA 上健康
   r4 = EVAL_SPLITS=test —— 分開跑，因為 test 的 first-run 只能拿一次，
        不能跟一個可能中途死掉的 round 綁在一起
   兩輪同一個 SHA，provenance 一樣強。

那個 degraded 檔留著，並且寫進 analysis report §5 正文，不要放附錄。理由：

這是整份提交裡唯一一筆真實的操作失誤證據，而系統的反應是 fail-closed。
沒安排、沒模擬、人為觸發：推了就是部署了，round 認出 SHA 變了、標成 degraded 並寫明原因，
.inflight 讓下次啟動拒絕而不是默默再花一次錢。
我們寫了二十五條 amendment 論證這個設計，這是它第一次在野外被觸發。
一個乾淨的 r2 只會多一行數字；這個檔案證明機制會動。三分錢換這個，划算。

寫的時候照實寫是誰造成的、怎麼造成的，不要寫成「模擬了一次中斷」。

■ 凍結期間你可以做的（不需要 push）

- 上面那段 analysis report §5 的補寫。
- r2 歸因的段落：明說 r2 同時含計分器修正與 A25.2/A25.3/記憶，r1→r2 的差
  並指向 artifact 重放作為量測效應的隔離證據。坦承混淆＋提出替代證據，
  比重跑一輪再宣稱乾淨更可信。
- 我剛修了 README 一處脫鉤（34a69f4）：§3 已縮成四筆承諾，§4 還寫著 "sev
  同類的請自己再掃一遍 —— 數字改了、論述沒跟著改的地方。
- 我接下來會對 README + analysis report 做逐句驗收（每一句對已建系統是否
  結果會給你。預期還有。

■ 順帶：你報告說「下一步做 OP-4 oracle」，那個你已經做完了（30f62f6，
harness.py:464 independent_oracle）。報告是舊的。A25.4 四條全部結清。
--------
另外，test split 的詳細步驟裡的步驟一你可以幫我做吧

==========
■ PM 逐句驗收結果：不能凍。一條 amendment + 四項封鎖 + 五項次要 + 一個必須現在回答的問題。

═══ 一、A26（我會寫進 spec §16）：DEV-04 的修法只做了一半

改記 response URL 只拿掉了時序，沒修好語意。

artifact_source_matches_plan 現在是拿「plan 凍結的目標」比對「最終落點」——
只要有重導向，這兩個天生就不相等。於是這道閘門只剩兩個選擇：放寬到永遠通過，
或對每一個 redirect 誤殺。那不是修好閘門，是換一個比較不會抖的巧合。
第 7 筆壞掉的儀器還沒修完，它只是換了個形狀。

要求：三個值都記 —— plan 的目標 URL、完整重導向鏈、最終 response URL。
閘門拆成兩個獨立斷言：
  (1) artifact 的來源 == 最終 response URL          （bytes 究竟從哪來）
  (2) 最終 URL 是從 plan 目標、經由記錄在案的重導向鏈到達的  （落點是否被解釋）

重導向鏈本來就存在 —— 每一跳都要重新驗 IP 是既有的 egress 規則 —— 只是閘門沒用它。
fixture 的 redirect 路由要同時涵蓋兩個斷言，不能只涵蓋 (1)：需要一個
「最終 URL 對、但抵達路徑無法解釋」的負向案例，否則 (2) 是個永遠通過的檢查，
那又是同一族缺陷。

這動的是 hard gate 的語意，走 amendment，不是 bugfix。
analysis report §5.4 第 7 列要跟著改寫成「發現 → 第一次修 → 修得不完整 → A26」，
不要寫成一次就修好。

═══ 二、封鎖項（凍結前必須清掉）

B-1  README §7 的 L-5 表格列，和 app/limitations.py 的 L-5 是兩件不同的事。
     表格寫 gutenberg.org 的 Science Fiction bookshelf；
     程式碼裡是 MDN Array/flat 的瀏覽器相容性表格。
     而且同一節往下三段的 bullet 自己就寫著
     「the entry moved to a page that does abstain (MDN's compatibility grid)」。
     我們在「每一條都對部署執行過」那一整節裡自打臉。這是最嚴重的一筆。
     修法：表格列以 limitations.py 為準（那是會被執行的那份），不是反過來。
     並且檢查 README §7 其餘六列有沒有同樣的來源分歧。

B-2  README §8「An SSRF probe is part of the safety suite.」
     對上 §7「The safety suite is not built.」—— 直接矛盾，方向是樂觀的，
     而且出現在安全章節。這就是 §5.4 第 5 類缺陷的重演。
     事實：egress guard 有測（tests/test_policy.py:49），M6 safety suite 沒建。
     改成指那支測試，不要指一個不存在的 suite。

B-3  README §7 的 L-7 列，task 欄和 What happens 欄配不起來。
     task 是 fixture 的無結果搜尋，What happens 寫「may abstain because our own
     page reduction dropped the element」—— 但 limitations.py 已經是
     no_result_verified（proven absence），下面的 bullet 也這樣說。與 B-1 同類。
     那一列要寫成：這個 task 現在證明了不存在；限制是「站在它背後、沒有
     empty-state 元素的頁面」。task 欄和 outcome 欄必須是同一件事。

B-4  錢的數字三處全過期，而且其中一句明確為假。
     README §7「Total provider spend across every scored round is USD 0.0477」
     docs/analysis-report.md §3.1「Total spend across all development USD 0.0477」
     docs/analysis-report.md §6「Total spend USD 0.0477」
     實際 ~USD 0.20（r2 dev 花了 ~$0.02）。「across every scored round」現在是假的。
     §5.5 的「Three cents was a good price」也要跟 §3 對得上帳，不要自己打架。
     這是我們對外唯一的財務數字。r3/r4 之後還要再更新一次，
     所以順手把它做成單一來源（ledger 檔），不要三個地方各寫各的。

═══ 三、次要（一併在凍結前處理）

N-1  r2 的 provenance 區塊缺席。README §6 給了 r1 完整的
     commit / model / tier / split-hash，然後直接公布 r2 的 9/11 卻沒有對應區塊。
     違反我們自己寫的「a score without them describes a system nobody can identify」。

N-2  README §3 support matrix 表頭寫「Status, from dev-deploy-aa1ee6c5d5eb-r2」，
     但 OP-7 那一格引的是 r1。表頭在說謊 —— 加註或拆欄。

N-3  README §6 結構：開頭宣告「The round below is r1」，然後同時報 r1 和 r2，
     讀者不知道哪個是 headline。r3 之後整節重寫，headline 只准指定一輪。

N-4  README §9 repository map 沒有 app/memory.py，
     但 §7 用一整段賣 locator memory。

N-5  「583 tests」用真實 collect 數字，加了 redirect 測試 + A26 的測試之後應該不只。

═══ 四、核過為真，不要動

FailureClass enum 實測 18 個、七個 terminal_status、§5.4 七筆 —— 都對。

§5.5 通過。照實寫了是誰、四分鐘後、推就是部署，沒有包裝成「模擬了一次中斷」。
§5.3.1 通過。而且這一句不准改：
  "the re-run would be a fourth build, and this document would have to explain
   why that one was single-variable"
那是整份報告最好的一句。

═══ 五、現在就要你回答的（會卡住 r3，不能到現場才發現）

r2 的 experimental 留了 .inflight，下次啟動會拒絕 —— 那是對的行為。
但 r3 是新的 EVAL_ROUND：那個 marker 會不會擋住 r3 的 experimental split？

如果 marker 以 split 為鍵而不是以 round 為鍵，operator 會在啟動 r3 時卡住，
然後在計分前的壓力下手動刪一個計分用的檔案 —— 那是最糟的時機做那個決定。

把處置路徑寫進 docs/runbook-scored-workload.md：是自動放行，
還是需要一個明確的操作動作、那個動作具體是什麼。現在寫。

═══ 六、流程

- 上述全部只 commit，不 push。
- Desktop 上的 validation 檔案不要動、不要串上去。它 unrun 才有價值，
  跑了就毀掉 README §6 的論述。
- 你改完 → PM 做第二次驗收（只看改動）→ PM 宣布 freeze SHA
  → 你 push 一次（那一次 push 就是凍結 build 的部署，兩個 service 都會換）
  → operator 進 dashboard 跑 r3（dev,experimental）
  → operator 再進一次跑 r4（test）。r3 和 r4 之間不准 push。
- 累計花費 ~USD 0.20 / 上限 10。不是限制因素，照品質做。

==========
第二次驗收：A26 判得對，canonical 那條比我要求的好，/detour 是整個 diff 最好的一段。
但還不能凍：三項封鎖，其中兩項在剛寫好的那道閘門裡。

═══ 封鎖

V-1  app/verifier.py:264 —— 修好第 7 類的同時把第 1 類種回去了。

     else:
         checks.append(Check("artifact_source_matches_plan", True,
                             {"source_url": ref.source_url, "scope": scope}))

     scope is not None 時這個 check 無條件回報 True，沒有比對任何東西。
     那就是你們自己 §5.4 表格第 1 列：「一個從未被評估過、卻被記錄為 satisfied 的約束」。
     而且名字叫 ..._matches_plan，讀者會以為比對過了。
     要嘛不 emit，要嘛 emit 成明確的 not-evaluated。
     在一份論證「我們的檢查是真的」的提交裡，這個不能留。

V-2  _how_the_landing_was_reached 在第一筆符合的 NAVIGATE 就 return，包含 return 失敗。

     迴圈最後那個 return {"explained": False, ...} 在迴圈「內」。
     只要 run 導向 target 兩次 —— recovery 換家族後重新導向、retry、離開後再回來 ——
     第一筆沒有 chain 也沒有 canonical 就直接判死，第二筆永遠看不到。
     recovery 重新導向正是這個系統設計上會做的事，不是理論路徑。
     要掃完所有符合的 entry，全部無法交代才回 False。加一支測試鎖住
     「第一次導向沒交代、第二次有」這個情境。

D-1  防止數字過期的機器，旁邊擺著一個會過期的總數。

     spend_ledger.py + --check 做得很好，三份文件也不再寫總數 ——
     除了 README §7 和 report §3.3 / §6 都寫著 "under a tenth of a dollar"。
     那就是寫在散文裡的總數。現在 billed 0.0798，
     r3（dev+experimental ≈ 0.048）+ r4（test ≈ 0.02）之後直接穿過 0.10。
     --check 抓不到散文。改成純粹連過去，或讓 --check 連這句一起管。

═══ 裁決：A-14b —— 留，但收窄

401/403/429 那半留著：免費、無啟發式、正確。

可見 password 欄位那半不能當終止閘門。它驗的是 presence 不是 substitution ——
頁面上有登入表單 ≠ 內容被牆擋住。而它會在 r3 計分 experimental split
（全是沒看過的站）之前上線，一個誤判就把一筆本來可能 verified 的 run 變成 blocked，
直接動到我們要公布的率。這是「一個回報巧合的檢查」，巧合是「password 欄位剛好在那頁上」。

收窄成：password 規則只能把一個本來就要失敗的 run 改分類，不能終止一個還走得下去的 run。
只在 run 已經要收在 locator_not_found / postcondition_unmet 時，
才用它把終局改成 blocked / site_unavailable。
這樣它只能往「修正錯誤歸因」的方向動，永遠不能製造新的失敗 ——
而且 README 那句「without it these runs ended as locator_not_found」
在收窄後才字面為真。

blocked / site_unavailable 用在登入牆語意上勉強，但凍結前不加新 failure class。
接受，訊息文字已有區分。

EXP-08 你判對了：在 r3 要計分它之前換掉 split 的身分識別不划算。不用改。

═══ 次要

V-3  gate 1 的 reached 集合把 canonical_url 也算成「run 到過的 URL」，
     而且沒有 gate 2 那層 same-origin + 只信 plan 目標頁的防護。
     canonical 是不可信頁面的宣稱，不是 run 到過的地方。gate 2 守得乾淨，gate 1 漏了。
     排除它或改名。今天不可獨立利用，但名字比它驗的東西寬。

V-4  docstring 說 chain「begins at the target … hop by hop」，
     程式只檢查 chain[-1]，沒驗連續性。改 docstring 或補檢查。
     別讓註解宣稱超過程式碼。

═══ 你問的兩個裁決

docs/task1-spec.md:2384 的 USD 0.0477 —— 不准動。凍結文本就是凍結文本，
那條紀律是我們整份提交在賣的東西之一。A26 我會寫一句：
該數字在寫下時為真，總額以 ledger 為準。這正是 amendment 存在的理由。

README 現在把 headline 定成 r2 —— 凍結檢查表加一條：
§3 support matrix 和 §6 的數字必須從 r3 重新生成後才能出貨。
現在 r2 的 OP-5「1 of 2」是 A26 剛修掉的那個閘門缺陷造成的，
等於在公布一個已知方向錯誤的數字。r3 跑完會對，但不能忘。
在 README 對應位置放一個 <!-- FROM-r3 --> 標記，我第三次驗收時對著標記檢查。

═══ 核過、不要動

.inflight 的答案完全正確，「不准刪」那段寫得比我問的好 ——
把它從「殘留狀態」重新定義成「已花費未完成的紀錄」是對的。
A26 的兩條斷言、canonical 的信任邊界、/detour、/soft-moved、
spend ledger 的 --check、§5.4 第 7 列改寫成
「發現 → 第一次修 → 前提是錯的 → A26」—— 全部通過。

這句留著：
  "a fix that merely stops it wobbling restores the appearance rather than the gate"

═══ 流程

改完仍然只 commit 不 push。回報後我做第三次驗收 —— 只看 V-1/V-2/V-3/V-4、
D-1、A-14b 收窄、FROM-r3 標記這七項，不重掃全文。
過了我就宣布 freeze SHA，你 push 一次，operator 才進 dashboard 跑 r3 → r4。

==========
改完 F-1、處理 F-2，然後直接 push。那一次 push 就是 freeze。 我不再做第四次驗收——邊際收益已經低於一天的日曆成本，而且 F-1/F-2 都不影響 r3 要量的東西。

有一件要寫進 report 的（可以 push 後補）：DEV-04 現在能通過，靠的是 Wikipedia 對自己的 rel=canonical 宣稱，同源守住。 那比一條重導向鏈弱——它是頁面自述，不是觀察到的事實。§5.4 那段值得補一句承認這件事，因為這正是這份文件在教讀者要問的問題。

七項全部核過。V-3 你反駁得有理 —— 實測 page_url_at_navigate 在 JS 改網址列前取值，
排除 canonical 會直接打死 DEV-04，把 gate 2 的信任邊界搬進 gate 1 比我的建議更好。
_chain_from 的三個條件、attempts 累積、unevaluated_checks、_terminate 裡的純改判、
D-1 的兩條規則、FROM-r3 的雙向測試 —— 全部通過。

兩筆新的，都是一行等級。改完直接 push，我不做第四次驗收。

F-1  login_form_visible 沒有進 store。

     app/executor.py:1226 把旗標寫在 nav.detail，但 _finish_step(run, nav, ...) 在
     _landed_somewhere_real 之前就已經存過了。之後這行只改記憶體物件，沒有 save_trace_entry。

     行為是對的（_wall_seen 讀記憶體中的 run.trace），問題在證據：
     stored trace、run 頁面、API、evidence bundle 都不會有這個旗標。
     於是終局訊息宣稱「A visible login form was standing on X」，
     而任何從儲存位元組重建這個 run 的人找不到任何支持它的紀錄。
     在一個論證「所有宣稱都能從 stored bytes 重新導出」的系統裡，
     那是一句沒有證據的宣稱。存下去。

F-2  unknown scope 現在是 fail-open。

     elif scope is not None 記了一筆 not-evaluated 之後就往下走，
     if scope is None 為假，完全沒有任何 artifact-source 閘門執行。
     一個 run 可以在來源閘門從未被評估的情況下拿到 succeeded_verified。

     命名誠實（進了 unevaluated_checks），但 M4 fail-closed inventory 的規則是：
     無法評估的硬閘門應該降級，不是放行。scope 來自我們自己的 compiler，
     只有我們自己寫錯 code 才觸發得到 —— 所以：
     要嘛改成 unverified / postcondition_unmet 收掉，
     要嘛在那裡寫一句話說明為什麼放行是對的。兩個我都接受，選一個。

═══ 裁決：條件式驗收通過

改完 F-1、處理 F-2，然後直接 push。那一次 push 就是 freeze SHA。
我不再做第四次驗收 —— 邊際收益已經低於一天的日曆成本，
而且 F-1/F-2 都不影響 r3 要量的東西。

push 之後你就進入 push-freeze：r3 和 r4 之間一筆都不准推。
operator 會做兩次 dashboard 動作，中間不需要你。

═══ 可以 push 後補的一件

DEV-04 現在能通過，靠的是 Wikipedia 對自己的 rel=canonical 宣稱，同源守住。
那比一條重導向鏈弱 —— 它是頁面自述，不是觀察到的事實。
analysis report §5.4 值得補一句承認這件事：
「這一筆的來源交代建立在頁面對自己的宣稱上，信任邊界是同源，
 而那是三條路徑裡最弱的一條。」
這正是這份文件在教讀者要問的問題，自己迴避掉就白寫了。

==========
先不要推。一件事必須在推之前做完，而且它現在就躺在 volume 上。

═══ 1. r4 沒有 evidence bundle —— 目前最嚴重的一件事

我們整個產品的論點是「失敗是可檢視的」，而最重要的那一輪、七筆非成功，
帶出 0 個 bundle。README §1、§4 和作業的 Common Requirement 都要求
讓失敗可檢視 —— 現在唯一一個 held-out 結果剛好是那個做不到的。
graders 會先點的就是那七筆。

不用改 code、不用重跑、不花錢：run 和 artifact 都還在 scored volume 上。
用你讀 spend readings 的同一條 ssh 路徑撈出來，commit 成 r4 的 bundle。
exporter 的修之後補（也該補，不然這是一次性搶救），但 bundle 今天就要進 repo。
每一次部署都是一次 volume 出事的機會，這批是 unrepeatable 的 first run，先落地再推。

註：held-out 內容進 repo 是 A14.5 已經規劃好的（提交時公布，雜湊先 commit），
而且計分已經取過了，污染的疑慮在 r4 跑完那一刻就結束了。不要再迴避讀它。

═══ 2. 1/8 就是那個數字。不改、不重跑、不換說法

95% 區間 0.02–0.47，照登。dev 10/11 對 held-out 1/8 的落差，
是這份提交裡資訊量最高的一筆數據，比任何一個高分都有價值。

但要拆對：八筆裡五筆從沒開始瀏覽。這個系統的瓶頸是它接受什麼，
不是它答對什麼。README §6 直接這樣寫，不要讓讀者自己從 failure class 表推。

補一個你沒點破的：三筆 robots_disallowed 是我們自己寫的 case
打到我們自己的政策。那既不是產品失敗也不是產品成功 ——
它是「我們對『一般任務』的直覺，比我們自己的政策寬」。
那是 §5.3.2 那個發現的最強證據，不是它的雜訊。寫進去。

═══ 3. §5.3.2 的位置放錯了

「我們的 split 量的是被接受的任務答得多好，而不是多少合理任務會被接受，
 而後者我們自己量不出來」

這是整個專案產出的最好的一句話，不該埋在 analysis report。搬進 README §6。

並且在 §3 support matrix 加一條已量測的警語（這條必須在承諾旁邊，
不能只留在第五節 —— support matrix 是我們對外的承諾，
而我們剛量到它在陌生措辭上只兌現一半）：

  T-DECLARED 的路由認得的，比這張表承諾的窄 —— held-out 上四筆宣告層 case
  有兩筆被路由成 T-EXPERIMENTAL。這與凍結前修掉的 OP-7 固定商品同一族：
  我們按 site × operation 承諾，實作認得的措辭比那更窄。我們自己的 dev split
  量不到這件事，因為那些 case 是由知道 router 吃什麼的人寫的。

═══ 4. §5.4 九筆、修好七筆 —— 對

「發現於凍結之後，不改 code，讓兩輪描述同一個 build」是正確的取捨。
寫明了就沒問題，不用回頭改。

═══ 裁決與順序

1. 撈 r4 的 bundle 進 repo（ssh，不改 code，不重跑）
2. §5.3.2 的核心句搬 README §6；路由警語進 §3
3. 然後推一次，全部一起送。三個 service 重新部署、無 code 變動，可以。
4. 推完 README 不准再宣稱部署的 SHA 就是計分的 SHA —— r3/r4 的 provenance
   自己帶著，說清楚就好。

花費 0.1515 / 8.00，不是限制。做完 1–2 再推，推完回報我做最後一次通讀。

==========
通讀完了，順便打了線上煙霧測試：/healthz ok:true、SHA 6f3ec87a354d、
/ /support /coverage 全 200 且 <1s、/api/eval-bundles 六輪都在、
r4 manifest 線上讀得到而且第一個欄位就是 rescued-by-hand/1.0。
文件我沒有再找到不實的句子。r4 的搶救做得好，manifest 自承來歷是對的。

但還有一件沒做，而且是最後一個真的洞。

═══ 1. eval/test-set.md 和 eval/validation-set.md 不在 repo 裡

eval/holdout-manifest.md:13 有預先 commit 的雜湊、
test-deploy-e82cacb9e809-r4.json 寫著 "eval_set_file": "test-set.md" ——
但那個檔案不存在於 repo。現在的狀態是：

  - 雜湊指向一個讀者拿不到的東西，驗不了
  - r4 的 provenance 指名一個 repo 裡沒有的檔案
  - 「這八題是 owner 寫的、ENG 沒看過」不可否證
  - 整份提交最強的那個發現（八取五沒開始瀏覽、三筆撞自己的 robots）
    grader 無法自己檢查

A14.5 本來就寫著：提交時公布，雜湊先 commit。現在就是提交時。
你為了對 case id 已經讀過 volume 上那份，直接從那裡搬進 repo，
然後跑一次雜湊比對 —— 必須對上 43ee8ce5…，對不上就是搬錯了。
holdout-manifest.md 的「in repo」欄跟著更新。

validation 也一起公布，旁邊寫「從未執行」。
那份檔案是「我們真的把它扣住了」這個紀律宣稱的唯一物證；
不公布的話，README §6 那段話跟沒說一樣。

═══ 2. 一處會被讀成矛盾的句子

README §6 experimental 段：verified 3/10 之後緊接著
「The pass count is unchanged from r1 at 4 of 10」。
verified 和 pass 是兩個不同的分母，中間沒有一句話解釋差別，
讀者會直接讀成前後打架。補一個從屬子句就好 ——
哪一筆是「狀態符合宣告但沒有 verified」而算進 pass 的。

═══ 3. 裁決：EXP-05 不要修

failed / internal_error 分類錯了、你記了、選擇不在凍結內修 —— 那是對的，
而且現在也不要修。現在改會讓部署的 build 在一個「結果檔有報導的分類」上
與計分 build 不同，那比留著一個誠實記錄的錯誤分類更糟。
留著，§6 已經寫明白了。

═══ 順序

1 → 2 → push 一次（純文件與資料，無 code）。
推完跟我說，operator 會去點一筆 r4 的失敗 bundle 確認 grader
第一個會做的動作是通的。然後就交。

明天是死線，這輪之後不要再開新東西。

==========
