# Task 1 — 通用瀏覽器自動化 Agent（精簡中文版）

本文為精簡中文版。完整論證與所有數字以英文版（README.md / docs/analysis-report.md）與 `eval/results/` 的結果檔為準。

用英文自然語言下任務，系統在真實瀏覽器上對公開、唯讀的頁面執行，回傳的只有兩種：**帶有驗證證據的答案**，或**誠實說明做不到什麼的非成功狀態**。

**線上系統：**<https://wf-agent.zeabur.app>
**前端頁面：**`/` 送出任務與近期 run · `/runs/{id}` 完整 trace · `/support` 支援矩陣與已知限制 · `/coverage` 證據覆蓋率 · `/healthz` 運作狀態

---

## 1. 一個核心想法

模型永遠不是「頁面上寫了什麼」的真相來源。多數 browser agent 的失敗方式相同：模型說「答案是 42」，系統就回報 42，錯了也沒有任何環節能察覺。這就是 **silent failure**，本題明確規定它比大聲失敗扣更多分。

1. **瀏覽前**：任務被編譯成 **postcondition**（必須成立的主張 + 必須真的發生的 UI 動作），雜湊後凍結，下游無法修改。
2. **瀏覽中**：每個關鍵頁面狀態存成 artifact（完整 DOM + text + 截圖），以 SHA-256 定址。
3. **瀏覽後**：模型的答案只是*假說*。決定性 verifier 重新打開已儲存的 artifact，嘗試把宣稱的值重新定位、並綁回任務指定的 label。若在儲存的 bytes 裡無法重新解析出來，該 run 就不算成功，無論模型多有信心。

關鍵句：**模型提案，決定性程式碼裁決，而裁決依據是儲存的 bytes 而非即時頁面。** 即時頁面會在答案與檢查之間改變，儲存的 bytes 不會。

兩個直接讓帳面數字變難看的後果：

- **絕不推論「不存在」。**「我找過沒找到」不是證明。`no_result_verified` 需要定位到 empty-state 元素，或有涵蓋整個結果集的 coverage anchor，否則 run 選擇棄權（這就是 L-3 的來源）。
- **用錯的方法拿到對的答案算失敗。** 若案例宣告必須送出表單，run 卻用猜測結果 URL 抄捷徑，即使值正確也判 **fail**。

---

## 2. 執行方式

### 使用線上系統

開 <https://wf-agent.zeabur.app> 輸入任務即可。首頁掛有預先執行好的 run（含失敗案例），不必等冷啟動就能檢視。

API：

```bash
curl -X POST https://wf-agent.zeabur.app/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"task": "On books.toscrape.com, open A Light in the Attic and tell me its UPC."}'

curl https://wf-agent.zeabur.app/api/runs/{run_id}          # 狀態 + 結果 + 證據 bundle
curl https://wf-agent.zeabur.app/api/runs/{run_id}/events   # SSE 進度串流
```

### 本機執行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium

export APP_ENV=development             # 僅為 loopback fixture 放寬 egress guard
export DATA_DIR=./.data/task1          # runs database + artifact store
export FIXTURE_BASE_URL=http://127.0.0.1:8801
export PROVIDER_KEY_DIR=./api_keys     # 目錄，金鑰從其中的檔案讀取
export PROVIDER_FREE_KEY_NAME=gemini_free_tier
export CREDENTIAL_POLICY=development
export PORT=8080

APP_ROLE=fixture PORT=8801 ./entrypoint.sh &   # fixture 是獨立行程，先啟動
./entrypoint.sh                                # app on :8080
```

**不需要 LLM 金鑰也能看到系統運作。** fixture 展示與首頁釘選的 run 走決定性路徑，完全不呼叫模型；需要金鑰的是模型驅動路徑，也就是所有非我們自建的網站。

**線上站台用哪一層憑證，以及那對你輸入的文字代表什麼。** 計分已經結束，所以公開站現在是
**免費層優先、被限流或用完時自動 fallback 到付費金鑰**（`CREDENTIAL_POLICY=public_demo_funded`，
累計額度 USD 2.00、每日 USD 0.50，每次呼叫前強制檢查）。兩層用的是同一個 pin 住的模型。
值得直接講清楚而不是讓人自己假設的是：**免費層的請求會被供應商用來改進它的產品。**
我們瀏覽的頁面內容依政策本來就是公開的，但**任務文字是送出的人自己寫的**——
所以你在 demo 裡打的字有可能走在免費層上。`/healthz` 會說明目前生效的是哪個政策、
哪些層在該政策下可用。

### 測試與評估

```bash
pytest                                    # 618 tests，約 20 秒（tests/test_m2_integration.py 會開真實瀏覽器）
python -m eval.harness --split dev
python -m eval.harness --split experimental
```

---

## 3. 承諾什麼，不承諾什麼

可靠度以 **`site × operation` 記錄**為單位承諾，絕不以「網站」為單位。每個任務在執行前就被指派 tier，tier 顯示在表單、結果與 API 回應中。

| Tier | 意義 | 計入頭條數字 |
|---|---|---|
| **T-DECLARED** | 命中下方承諾記錄 | **是** |
| **T-EXPERIMENTAL** | 其他公開、政策乾淨、唯讀網站。盡力而為，棄權是正確結果 | **否**，另外分開報告 |
| **T-REFUSED** | 違反 §5 政策，瀏覽前就拒絕 | n/a |

### 支援矩陣

**承諾集是四筆，不是七筆。** OP-1…OP-3 跑在我們自建的 fixture 上，等於自己出考卷考自己，因此**撤出承諾**，只保留為 mechanism evidence（`/support` 的 GS-1…GS-3），不計入任何成功率。

| ID | 站點 | 操作 | 狀態（`r3`） |
|---|---|---|---|
| OP-4 | en.wikipedia.org | 依指定欄位排序 wikitable，讀新的首列 | **3 個 dev 案中 2 個符合預期。** DEV-01 有獨立推導的首列，**8 個 cell 全部一致**；DEV-03 的欄位 oracle 在該頁找不到，報告為「未推導」而非「已檢查」；DEV-02 以描述而非標題指名文章，正確地在瀏覽前停止（見 L-1） |
| OP-5 | en.wikipedia.org | 展開摺疊區塊/navbox 並讀出原本看不到的值 | **2/2。** DEV-04 在 `r2` 是被 artifact-source gate 判失敗而非操作失敗；Amendment 26 重建該 gate 後通過，且是走三條路徑中**最弱的一條**（分析報告 §5.4 有說明）。**無獨立 oracle**，正確性只靠我們自己的 verifier（A25.4） |
| OP-6 | books.toscrape.com | 走訪分類、翻頁、抽取清單層級事實 | **2/3。** 第三個在長分類上耗盡 step budget、不給答案（L-2），三輪皆如此 |
| OP-7 | books.toscrape.com | 開產品詳細頁抽取**帶 label** 的欄位（UPC、Availability、Price excl. tax） | **2/2**，且是產品參數化之後第一次計分：從任務取書名、翻列表頁抵達，上限 6 頁。超出上限會以 `unsupported` 結束並說明界線，而不是回報錯誤的書 |

`r1` 六個 evidence finding 中有四個是 harness 自己跟自己不一致（只比對 rendered text，而 `books.toscrape` 的長標題在 `title` 屬性裡，產品讀得才對）。`r2` 這四個消失，剩兩個都是 tier 分歧。`r1` 仍然保留在版本庫中作為紀錄。

> **已量測的警告：指派 `T-DECLARED` 的 routing，認得的東西比上表承諾的少。** 在 held-out split 上，**四個 declared tier 案例有兩個被線上系統路由到 `T-EXPERIMENTAL`**，根本沒碰到承諾的表面。這與 OP-7 固定產品的缺陷同一族：我們以 `site × operation` 承諾，實作卻只認得更窄的一組**措辭**。我們自己的 dev split 量不到這件事，因為那些案例是由已經知道 router 接受什麼的人寫的。上表每一列都應視為「條件成立於任務剛好用我們預期的方式措辭」。

### 承諾有語言限制

宣告的承諾**只涵蓋英文任務**——公布的成功率不含中文，因為評測集全是英文。但中文不是走不通：四項承諾的中文措辭路由層認得，實測可到 `T-DECLARED` 並通過驗證（見 `docs/grader-guide.zh-TW.md` 步驟 2）。沒被翻譯的是必須對上頁面文字的值（欄位標題、分類名稱），請照頁面拼寫。**沒評估過的東西不算承諾，但也不等於做不到。**

---

## 4. 關鍵設計決策

**postcondition 在瀏覽器開啟前就凍結並雜湊。** 代價：run 可能因為我們問錯問題而失敗，但那個失敗是看得見的。

**驗證在儲存的 artifact 內重新解析，不看即時頁面。** 任何持有該 run artifact 的人（包含評審，透過 `/api/artifacts/{id}`）都能重跑檢查。

**值與 label 結構性綁定。** 頁面某處出現的字串不等於「UPC 是什麼」的答案。

**Tier 存在，是為了讓「它在任何網站都能用嗎」有一個數字可答。** 代價是頭條數字覆蓋的面積比含糊的產品小，撤掉三筆 fixture 記錄後又更小。

**retry 與 recovery 是兩件事，系統從不混用。** 同策略重跑只記為 retry，不算 self-correction。*recovery* 是換到不同策略族（accessibility tree → text anchoring → structural → alternate route → alternate representation），且必須由封閉集合中一個**具名的診斷原因**觸發；「這步丟了例外」不算診斷。截圖座標點擊是最後手段，且在 planner 邊界直接拒絕。

**budget 採 fail-closed。** 耗盡即 `budget_exhausted` 且不給答案，而不是把剛好走到的頁面當成最後一頁。L-2 就是這個決策以限制的形式現身。

**每個非成功都帶封閉集合中的 `terminal_status` × `failure_class`。** 7 種 status、18 種 failure class，只能以書面修訂擴充。`partial` 與 `unverified` 在產品任何地方都不會被算成、也不會被描述成成功。

**選 books.toscrape.com 是因為它的自動化政策毫無歧義。arXiv 被放棄**，因為其 robots 政策 disallow `/search`、`/find`、`/form`、`/api`，而那正是我們想做的操作。`robots.txt` 比對是真正的 RFC 9309 實作，有專屬 CI job。

**公開部署為唯讀、每一跳都重新驗證目標 IP、所有頁面文字視為不可信資料。** 頁面文字永遠不能改變目標、tier、政策、budget 或 memory；這是結構性強制（memory 只餵給 locator 解析，不會以自由文字注入 planner），不是靠拜託模型。

---

## 5. AI 幫上什麼，沒幫上什麼

整個系統由 AI session 加一位人類 product owner 建成。

**分工。** 兩個角色刻意分離的 Claude Code session：**product owner / acceptance session** 負責 spec、驗收準則與裁決，從不寫產品程式碼；**engineering session** 依凍結的 spec 實作，從不決定什麼叫「正確」。同時定義成功又回報成功的單一 session 一定會回報成功——那與「既回答又自我驗證的 agent」是同一個缺陷，只是高了一層。`docs/task1-spec.md` §16 是紀錄：spec 的每一次變更都是附加在凍結文字後的編號修訂，並附上觸發它的缺陷。

**AI 明顯擅長的**：決定性 verifier、RFC 9309 robots matcher、evidence store、taxonomy 管線——規則密集、邊界銳利的程式碼。以及對抗式閱讀：好幾條修訂來自一個 session 找到另一個 session 的缺陷。

**具體不擅長的**：本專案有三個由 AI 產生、且只有靠獨立 AI review 實際跑線上系統才發現的缺陷：

- 一條已發布的限制（L-1），其列出的 workaround **根本無效**，三十秒即可重現。
- 一筆承諾記錄（OP-7）被寫死在單一產品上，使**支援矩陣**對其他所有產品都是假的。
- evaluation harness 宣告了**沒有實作**的獨立 oracle，讓我們最強的正確性主張變成不可證偽。

三者模式相同：**流暢、結構正確、語氣肯定、沒有對照現實檢查過。** 每一個都是關於系統的*主張*而非程式的 bug，正是針對程式碼的 review 抓不到的那一類。有效的對策是把線上系統當成對手來跑，而不是讀 diff。

**人類承重的地方**：決定砍什麼、拒絕用點狀修補處理應該整類處理的需求、以及花錢或改變承諾的決定。Amendment 25（做減法）最清楚：AI session 會一直繼續蓋下去。

---

## 6. 評估

四個 split，全部由我們針對公開頁面撰寫。每個結果檔都自帶 provenance：git SHA、釘選模型、credential tier、以及所評分 split 檔的 SHA-256。完整數字在 `eval/results/` 與 `docs/analysis-report.md`。

**頭條輪次是 `r3`**，對凍結的送審 build `e82cacb9e809` 計分。三輪全部保留在版本庫中，因為刪掉不同意的輪次後才活下來的數字不是量測。

**線上部署不一定就是這些輪次所計分的 commit**，本文不作此宣稱：計分凍結 build 為 `e82cacb9e809`，而線上跑的是哪一個 commit 請以 `/healthz` 的 `git_sha` 為準——**這裡不寫死一組要你去比對的代號，請記下你當下看到的那一組**。`e82cacb9e809` 之後的 commit 絕大多數是結果、證據與文字；有程式碼的是分析報告 §5.4 第 11–15 筆缺陷的修正（執行詳情頁回 500、進度顯示卡住、以及三處頁面對自己的描述過期），全部不動任何一輪的數字。權威來源是各結果檔自己的 provenance（`eval/results/*-r3.json`、`*-r4.json` 的 `git_sha`），不是執行中的容器。多跑幾輪來拉近距離＝把 held-out split 跑第二次，那是唯一不能做的事。

| | `r1` | `r2` | **`r3`** |
|---|---|---|---|
| 是什麼 | 對部署的第一輪 | 在修正後的 harness 上重評 dev | **凍結 build，兩個 split** |
| Commit | `e1d13cae4926` | `aa1ee6c5d5eb` | **`e82cacb9e809`** |
| 模型 | `gemini-3.1-flash-lite` | 同左 | 同左 |
| Credential tier | paid | paid | paid |
| Dev split 檔 | `8f584218…` | `9c1a0dee…` | `9c1a0dee…` |
| Experimental split 檔 | `790d9440…` | *中斷 — 分析報告 §5.5* | `790d9440…` |
| 執行時間 (UTC) | 2026-07-28 14:26–14:31 | 2026-07-28 17:05–17:07 | 2026-07-28 18:58–19:04 |
| Dev 頭條 | 6/11 | 9/11 | **10/11** |

**Dev split — 15 案，14 案為 declared。** 14 案中有 13 案結束於該案宣告可接受的狀態。唯一沒有的是產品選擇拒答而非猜測：DEV-08 在長分類翻頁時耗盡 step budget、不給答案（L-2），每一輪皆如此。

**頭條通過率 10/11**，比狀態計數低，因為要通過必須狀態符合預期*且* harness 能在儲存的 artifact 中重新定位每個已驗證的值。全 split 仍有兩個 evidence finding，都是 tier 分歧（DEV-02、DEV-13），與數值無關。

**輪次之間的變化不是一個故事。** `r1` 的 6/11 主要是*我們的評分器*有錯：五個 miss 中有四個是 harness 只搜 rendered text。`r2` 的 9/11 修好了這點，但**不是單一變因**：該 build 同時帶進 OP-7 參數化、n-claim postcondition 與 locator memory（分析報告 §5.3.1 直說）。真正把量測缺陷與產品改動分開的是 artifact replay：用 r1 自己儲存的 bytes、在修正後的 corpus 下重檢，恰好解釋了 r1 五個 miss 中的四個。

`r3` 相對 `r2` 唯一的進帳是 **DEV-04**，而且方向相反：該案在 `r2` 本來是*正確的*，卻被我們自己的 artifact-source gate 判失敗（凍結的目標 URL 對上 Wikipedia 已移動的頁面）。Amendment 26 把 gate 重建為對已記錄 redirect chain 的兩個斷言，該案通過，但**是走三條路徑中最弱的一條**——頁面自己宣告的 `rel=canonical`，限制在 same-origin。

**唯一一個「本來可以抓到錯答案、確實跑了、而且一致」的檢查**：DEV-01 的首列由 harness 獨立推導（自己抓文章、依欄位自身的值判定數值排序或字典排序、排序、比對），**8 個 cell 全部一致**。DEV-03 的欄位 oracle 在該頁定位不到，報告為*未推導*。

**Experimental split — 10 案，全在我們從未碰過的網站上。** 嘗試 10/10；**verified 3/10**（95% Wilson **0.11–0.60**）；看過後棄權 3/10；失敗或被擋 4/10；政策拒絕 0。通過數與 `r1` 相同（4/10，且是同樣四案）——**`verified` 與 `passed` 是兩種量測**，差別在 EXP-03：該站不發出 empty-state 元素，因此*拒絕下結論*才是案例宣告的正確結果，它以 `failed / locator_not_found` 結束，符合預期所以 passed；但什麼都沒驗證，所以不在 3 之內。

有變的是兩個失敗的*分類*，其中一個是對我們自己的 finding。EXP-10 從 `unsupported` 變成 `failed / budget_exhausted`（比較準確）。EXP-05 從 `unsupported` 變成 **`failed / internal_error`**：planner 提出一個不在它收到的 view 裡的 element reference，run 選擇拒絕而非依模型憑空發明的 ref 行動。拒絕本身是對的，就是該有的 fail-closed 控制；但**分類是錯的**——`internal_error` 意指我們自己的缺陷，模型發明 ref 不是。這與 Amendment 26 的 A-14b 半邊要修的歸因錯誤同種，發現時已來不及在凍結內修正，因此記錄於此而非事後靜悄悄修掉。

那些棄權是產品在運作，不是產品在失敗。10 案是很小的樣本，那個信賴區間就是檔案自己說出這件事。

**Test split — 8 案，held-out。在凍結 build 上只跑一次（`r4`）：1/8。**

| | |
|---|---|
| 全部案例 | **1/8** — 0.125，95% Wilson **0.02–0.47** |
| Declared tier 案例 | **1/4** — 0.25，95% Wilson **0.05–0.70** |
| Failure class | `robots_disallowed` 3（**全部是同一次暫時性抓取失敗，見下**）· `policy_refused` 2 · `budget_exhausted` 1 · `postcondition_unmet` 1 · 一個成功 |
| Build / split | `e82cacb9e809` / `test-set.md` `43ee8ce5…`，第一案前先驗雜湊 |
| 執行時間 | 2026-07-28 19:21–19:22 UTC |

**這是整份送審被衡量的數字，遠低於 dev split 的 10/11。那個落差本身就是 finding，不是註腳。** 案例由 product owner 撰寫、engineering session 從未看過——這正是它們有能力反駁我們的原因，而它們也真的反駁了。

**八案中有五案從未瀏覽**，但這五案分成兩種：三案敗於暫時性 `robots.txt` 抓取失敗（見下），兩案因任務沒指名起始頁面或站點而被拒（L-1 的 entry-point 限制，是系統真實的性質）。因此 `r4` 誠實的讀法是**它量到的可用性不亞於能力**，1/8 是下限而非估計值。但它仍然是分數：第一次執行即為回報分數（S-10.6），不重跑，不因為考差就重考。

> **我們自己的 split 量的是「系統對它接受的任務答得多好」。held-out split 量的是「它到底接受多少合理的任務」——而後者是我們自己產不出來的數字，因為我們寫的每一個案例都出自已經知道 router 吃什麼的人。**

**剩下五案說了什麼、沒說什麼。** 撇開三個逾時案，`r4` 剩五案：兩案在 admission 被拒（未指名頁面或站點）、兩案瀏覽後在能力上失敗（`budget_exhausted`、`postcondition_unmet`）、一案 verified。「進不去」與「做不對」剛好各半，但 **n=5** 太少，不足以指認瓶頸——本節的早期草稿曾經指認了一個。上面的 tier-routing finding 不依賴這點，自有證據支撐。

- **三筆 `robots_disallowed` 完全不是政策發現，而是一次暫時性網路失敗；把它們讀成政策覆蓋是我們自己的錯誤**，是點開我們剛發布的證據才抓到的。三筆同一個 host、同一個成因：round 進行中 `books.toscrape.com/robots.txt` **抓不到**（`urlopen error timed out`），而抓不到 `robots.txt` 依設計就是拒絕。沒有任何 `Disallow` 命中。該站**根本沒有 `robots.txt`**——它回 404，我們的 matcher 讀成不受限；二十分鐘前的 `r3` 有七案就是這樣跑的，現在再跑也是 0.6 秒完成。**八個 held-out 案有三個，敗給一個我們承諾的站點上約 78 秒的網路事件。**
- **三筆 tier 分歧，而且方向不利。** 兩個 owner 宣告 `T-DECLARED` 的案例被線上系統路由到 `T-EXPERIMENTAL`，另有一個宣告 `T-REFUSED` 的也落到 experimental。**承諾 tier 的案例有一半沒碰到承諾的表面。** 這與 OP-7 固定產品參數是同一缺陷類別。

> **如果你自己跑任務時看到 `blocked / robots_disallowed`，先打開 trace 再下結論。** 該步驟的 `robots` 紀錄區分了這個 failure class 沒區分的兩件事：
> - `"source": "rule"` — 站點的 `robots.txt` 確實禁止該路徑，命中的規則會引用在旁邊。
> - `"source": "unfetchable"` — **我們讀不到政策**，所以拒絕瀏覽規則沒看過的站點。這是 fail-closed 在運作，不是站點說不。
>
> 這不是假設：我們自己的 held-out 輪次就發生三次，在 `books.toscrape.com` 上——一個**完全沒有 `robots.txt`** 的站點。它是分析報告中的缺陷 10。

- **唯一跑到答案的 declared 案例通過了。** 四個 declared 案例中：一個產出 verified 答案、一個耗盡 step budget、兩個在那之前就被錯誤分 tier。

**該輪沒有匯出任何 evidence bundle，是人工救回來的。** held-out 結果在寫檔時就抑制逐案細節（S-10.4），而 bundle exporter 讀的正是那個被抑制的結構——於是有七個非成功的那一輪帶著**零**個 bundle，偏偏是最值得檢查失敗的那個 split。沒有東西遺失：run 與 artifact 都在計分服務的 store 裡，`eval/results/bundles/test-e82cacb9e809-r4/` 現在含**全部八案的完整 trace 與 24 個 artifact**，雜湊已對 store 的紀錄重新驗證。該目錄的 manifest 自己聲明它不是由 exporter 產生的。

八案中有五案沒有 artifact，這是結果而非救援的缺口：那些 run 在任何導覽前就被拒絕，沒有頁面可擷取；對拒絕而言，證據*就是* trace——命中的規則、被比對的 URL、以及 run 停在哪裡。

**Validation split — 刻意未執行。** 它的用途是在開發*期間*藉由對 engineering session 保留案例來維持誠實。開發已結束，現在跑只是買一個數字，而不是它存在的紀律（Amendment 25）。以「未執行並附此理由」回報，而非默默略過。

**兩個 held-out split 現已公開。** `eval/validation-set.md` 與 `eval/test-set.md` 都在版本庫中；其 SHA-256 在**任一被執行之前**就已 commit 於 `eval/holdout-manifest.md`，而 `test-deploy-e82cacb9e809-r4.json` 的 provenance 帶著同一個雜湊。`shasum -a 256 eval/test-set.md` 可自行閉環。兩個後果我們主動說明：

- **test split 從此是回歸測試組，不再是 held-out 集。** 它已被讀過，未來任何來自它的數字都不具第一次執行的權威（S-10.6）。
- **validation 以未執行的狀態公開**，那是我們真的有保留它的唯一實體證據。

**兩道硬性 gate。** Verified-but-wrong = **0**：三輪之中，沒有任何 run 回傳過被獨立重檢發現與 artifact 內容不同的值——而在 `r3`，這句話背後有一個案例是真的把正確答案*推導*出來（DEV-01，8 cell 一致）。Evidence coverage：每個標記為 verified 的主張都帶著它被重新抽取自的 artifact id 與 SHA-256。

兩句話都比看起來的窄，而變窄的部分才是重點：

**oracle 實際檢查什麼（A25.4）。** dev set 的案例註記曾描述獨立 oracle（「harness 抓表、套用相同排序鍵、比對」），那些**從未被實作**。`check_evidence` 實際做的是：重抓 artifact、對已記錄的 digest 重新雜湊、在其中重新定位每個宣稱的值——這是對*支撐主張的證據*的真實獨立檢查，**不是**對正確答案的推導。在 `r1`，這讓 OP-4 與 OP-5 的 `independently_checked` 停在 **0**，也就是說「verified-but-wrong = 0」恰好在最要緊的地方不可證偽。

**OP-4 現在有推導了，`r3` 是它第一次實跑的輪次。** harness 自己抓文章、找到帶指定欄位的表、依該欄自身的值判定數值或字典排序、排序、比對首列；不一致就是對該案的 finding。這個判定正是 DEV-02 設計要踩的陷阱：以文字排序時，CIK `0000001800` 與 `0000320193` 的順序與數值排序不同，而兩種順序在頁面上看起來都很合理。

**OP-5 仍然沒有**，報告直說而非暗示有：展開摺疊區塊是只在互動後才存在的狀態，純抓取會與一個正確的 run 不一致。`eval/dev-set.md` 中每個案例的 `oracle` 欄位現在指明它受哪一種檢查——*獨立推導*、*evidence 重檢*、或 *trace 檢視*——而不是十五案全都宣稱第一種。

**我們對 held-out 集的預期與實際。** 我們預期 declared 記錄會如矩陣所述、未見過的任務棄權多於作答。結果是：declared tier 案例有一半根本沒抵達所宣告的表面，而主導結果是**瀏覽前的拒絕**而非看過之後的棄權。預期錯得很具體、也很有用：我們量的是系統對它接受的任務答得多好，不是它接受多少合理的任務。`r4` 量的是後者，也是評審會實際感受到的那個。

---

## 7. 已知限制

即時清單在 **<https://wf-agent.zeabur.app/support>**，而且不是散文：每一條都是**你可以貼進輸入框的任務**，加上系統實際的反應與原因。每一條都已對線上系統執行並照著寫的方式重現——兩天前還不是如此，這正是這條規則存在的意義。

| | 任務 | 實際發生什麼 |
|---|---|---|
| **L-1** | *"In the S&P 500 constituents table on Wikipedia, sort by CIK ascending…"* | 瀏覽前停止：`unsupported / policy_refused`。文章是被描述而非指名。**指名了也沒完成**：改成 *"In the List of S&P 500 companies article on Wikipedia, …"* 能找到正確的表並排序，卻無法辨識排序已完成，把剩餘步數花在重新搜尋文章：`failed / budget_exhausted`。兩半都對線上部署執行過；本條的早期版本曾宣稱第二半成功 |
| **L-2** | *"How many books are listed on the last page of the Nonfiction category on books.toscrape.com?"* | 翻頁時耗盡 step budget，**不給答案**（`failed / budget_exhausted`）。翻到「最後一頁」每頁要一次模型呼叫。budget 刻意 fail-closed |
| **L-3** | *"Is there any book in the Fiction category on books.toscrape.com priced over £50?"* | 只讀到清單自報 65 本中的 20 本，回報覆蓋**未證明**（`unverified`）。不存在只從正面證據推得，而多頁分類跨多個 artifact、本 build 只對單一 artifact 驗證。單頁分類可以回答 |
| **L-4** | *"Use Wikipedia's search page to find articles mentioning 'convertible arbitrage'."* | 導覽前拒絕（`blocked / robots_disallowed`）並引用規則。Wikipedia disallow `/wiki/Special:Search`。拒絕是正確的**同時**也是限制：一個沒有合法路徑的普通問題在這裡沒有答案 |
| **L-5** | *"On developer.mozilla.org/…/Array/flat, tell me the Chrome version listed in the browser compatibility table."* | 瀏覽後棄權（`unsupported / postcondition_unmet`），指明步驟、頁面與未滿足的 postcondition 部分。該值位於 label 是圖示與欄位位置而非文字的格線中，沒有東西可供程式重讀。**本條取代了一個開始會成功的 Project Gutenberg 任務**：發布一個已不再發生的棄權，與發布一個從未有效的補救是同一種缺陷 |
| **L-6** | *"Go to the nonfiction category listing on books.toscrape.com and read the second page of results, without the planner."* | 正確作答（`succeeded_verified`），但**走決定性路徑**。兩條路徑滿足相同 postcondition、驗證方式相同，但迴圈中沒有模型，所以這不是 self-correction 的證據。每個 run 都記錄自己的路徑，比率分路徑回報 |
| **L-7** | *"Search the fixture catalogue for a term that appears on no page"* | **證明不存在**（`no_result_verified`）：定位到 empty-state 元素、計數器回述凍結的搜尋詞。限制在其背後——**沒有 empty-state 元素的頁面**，那裡的棄權可能是我們自己的頁面縮減把元素丟掉造成的，而非站點本身。那些 run 會被稽核與標記，而稽核只涵蓋我們想得到要看的東西 |

**實際執行這份清單發現了什麼。** `python -m eval.limitations_check --base-url https://wf-agent.zeabur.app` 會對線上系統跑每一條（含宣稱的補救措辭），寫出 `eval/results/limitations-<sha>.json`。第一次執行時，**七條裡有四條沒有照著寫的方式重現**：

- L-1 的補救失敗（如上），就是獨立 review 找到的缺陷。
- L-4 發布為 `policy_refused`；實際結束於 `robots_disallowed`，後者較準確。
- L-5 的 Project Gutenberg 任務已開始**成功**，於是改到真的會棄權的頁面（MDN 相容性格線）。
- L-7 的 fixture 搜尋現在會透過 empty-state 元素**證明**不存在，而非棄權。

它還抓到一個沒有任何測試抓到的回歸：Amendment 24 加的 accessibility snapshot 佔了自己的 trace entry，而每個 trace entry 都計入 step budget，於是擷取密集的 run 只剩下設計時一半的瀏覽餘裕。現在一次擷取重新等於一步。

**還有一個，是把同一 split 評分兩次才發現的。** DEV-04 在輸入沒變的情況下 `r1` 通過、`r2` 失敗：run 凍結的目標是 `/wiki/Apple_Inc`，證據來自 `/wiki/Apple_Inc.`，而導覽步驟記錄的是*讀取 `page.url` 那一瞬間*的位置——一個正確的 run 對著自己的 artifact 沒通過「證據來自計畫頁面」的檢查。第一次修法（改記 response URL）是錯的：實測 `/wiki/Apple_Inc` 回應 **200 且完全沒有 redirect**，網址列兩秒後才由站點的 script 改掉，這樣修會把閃爍的失敗變成永久的失敗。**Amendment 26** 把 gate 拆成對三個記錄值的兩個斷言。完整說明在分析報告 §5.4。

**OP-7 的參數化。** 該記錄承諾的是「開產品詳細頁抽取帶 label 的欄位」，但其計畫寫死在單一產品上——問任何其他書的 UPC 都是同一操作卻落到 T-EXPERIMENTAL。記錄是 `site × operation` 且頁面是參數；被實作縮窄的承諾是一份錯誤的支援矩陣，不是 tier 標籤細節。現在產品名由任務決定，run 像人一樣從列表往後翻抵達，**上限 6 頁**（該站沒有搜尋）。不在那些頁裡的書名以 `unsupported / postcondition_unmet` 結束並說明界線與建議分類，這是殘存的限制。OP-4、OP-5、OP-6 已檢查過同一缺陷，其文章、欄位、方向、分類與頁碼都已取自任務。

### 沒有做、也不宣稱有做的

以下每一項都是在剩兩天與固定預算下作出的決定，記錄為決定而非被發現的缺口（Amendment 25），最後一項除外——它建到明說的最低限度，界線就是條目本身。

- **Task 2（SEC 10-K 抽取）未建。** `docs/task2-seam.md` 是它完整凍結的契約（解析規則、修訂排序、上限行為、雜湊），而契約背後什麼都不存在。作業只要求一個 task，為一個不會存在的產品做完整介面規格是對會存在的那個做減法。以「已設計、未建置」的接縫發布。
- **Self-maintenance（§8，locator memory）是縮減版。** volume 上一張以 `(origin, operation, role)` 為鍵的表，**只**從 `succeeded_verified` 的 run 寫回（絕不因為「點得到」就寫），14 天確認窗、連續三次失敗即隔離、`/healthz` 有計數器、run 頁面標記每次互動是 *from memory* / *healed* / *freshly derived*。**計數器多半是「有存、但一次都沒被查詢」（`rows_stored` 有值、`uses`／`hits`／`heals` 為 0），那正是健康部署的樣子**：記憶體只在 locator 停止解析時才介入，所以頁面沒改版時這些數字就不該動；已寫入的列數證明寫入路徑是活的，所以那是量到的零，不是沉默的零，`/healthz` 會把這句話寫在計數器旁邊。儲存的是元素身分、絕不是值；記住的 locator 一樣要重新解析與重新驗證：它省的是搜尋成本，不是證明。未建：跨站泛化、排序、學習式 selector 模型、或把 memory 當第一選擇。
- **Mutation suite 是兩個 mutation，不是九個。** MU-4/5/7/9 與 sweep 全砍。兩個可用 mutation 加一個 healing 展示是證據，九個是研究計畫。
- **Safety suite 未建。** 存在的（egress guard、robots 強制、拒絕分類）都承重且有測試；不存在的是 safety split 與 injection detector，所以 `injection_detected` 是一個**沒有任何程式路徑會抵達**的宣告狀態，`/coverage` 直接這樣寫——標成**未建、不帶里程碑、也永遠不算逾期**，因為把砍掉的工作顯示成排程中，等於許一個我們不會兌現的承諾。那一頁在最後一天之前確實寫著「due at M6」（第 13 筆缺陷）。另外要說明的是：那一頁的 `gate_passes` 仍是 false，後面掛著十個標成 overdue 的 failure class。**那是誠實的讀數，不是缺陷**——那十個在這個部署上真的沒被產生過，而那正是這一頁要講的事。
- **Spend 控制就停在原地。** 本庫所有花費總額都生成到單一檔案 [`docs/spend-ledger.md`](docs/spend-ledger.md)，因為三份文件各自帶一個數字，就是三個在同一天過期的數字。上限、ledger 與 credential 拓撲都完成了，而 ledger 也是讀者看出它「做過頭」的地方。
- **執行期 `blocked` 偵測建到最低限度，且兩半刻意權力不同。** 認證與付款類任務在任何導覽前就以 `unsupported / policy_refused` 拒絕（*我們不做這種事*）；run *進行中*遇到的障礙是*有東西擋住我們*，以 `blocked` 結束。**HTTP 401/403/429 會結束該 run**（狀態就在回應上，不需啟發式）。**看得見的登入表單不會**：它只會把一個已經在失敗的 run 從 `locator_not_found` 或 `postcondition_unmet` *重新分類*——這正是它要修正的歸因錯誤，也是規則萬一錯了不會有代價的那個方向。理由是：可見的密碼欄只證明登入表單*存在*，不證明內容被它取代。以外觀辨識 paywall 則完全不嘗試。

---

## 8. 政策與安全

- **唯讀。** fixture 以外不送出表單、不認證、不寫入。
- **`robots.txt` 是強制執行而非參考** — RFC 9309 比對語意，有專屬 CI job。被禁路徑產生 `blocked / robots_disallowed` 並引用規則。
- **每次導覽都重新解析並重新檢查目標 IP。** 私有與 loopback 範圍一律拒絕（含經由 redirect），拒絕訊息會指名範圍。案例在 `tests/test_policy.py`：loopback、RFC 1918、link-local `169.254.169.254`、IPv4-mapped private、CGNAT、非 http scheme，外加 production 若關掉 guard 就啟動失敗。那是一個測試檔，不是 §7 說未建的 safety split：沒有 injection detector，也沒有對抗式 sweep。
- **頁面文字是不可信資料**，永遠不能改動 goal、tier、policy、budget 或 memory。
- **只有公開資料會送給模型供應商**，前面有本地 gate 阻擋憑證、token 與私有 URL。
- **任何 log、trace 或 prompt 紀錄中都不會出現憑證。** 金鑰從版本控制外的檔案載入。
- 所有使用的站點皆為公開，所有評估案例皆由我們針對公開頁面撰寫。

---

## 9. 版本庫地圖

| 路徑 | 內容 |
|---|---|
| `app/` | 系統本體。`postcondition.py` 凍結、`executor.py` 瀏覽、`verifier.py` 是 gate、`suspicion.py` 稽核安靜的結果、`memory.py` 是 locator memory、`robots.py` + `egress.py` 是政策邊界 |
| `fixture/` | 我們自建的站點：POST-only 搜尋、JS 分頁、阻擋式覆蓋層、injection 頁面 |
| `eval/` | harness、dev 與 experimental split、結果、provenance、`oracles.py`（OP-4 的獨立推導）、`spend_ledger.py` |
| `docs/task1-spec.md` | 凍結的工程 spec 與其修訂（27 條）。**推理軌跡在這裡** |
| `docs/task1-discovery.md` | 最初的探索推理，刻意不更新 |
| `docs/analysis-report.md` | 效能、成本、可擴展性，以及正確性如何驗證 |
| `docs/task2-seam.md` | Task 2 的契約——已設計、刻意未建（Amendment 25） |
| `prompts/` | 給每個 session 的每一則 prompt，逐字保存 |
