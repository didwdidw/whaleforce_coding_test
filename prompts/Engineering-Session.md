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
