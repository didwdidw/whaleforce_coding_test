# 獨立驗收報告

審查者：獨立 reviewer（read-only，使用者／評分者視角，未讀任何產品程式碼）
對象：<https://wf-agent.zeabur.app>，`git_sha` **7bfa5d2c3185**（與本機 HEAD 相同）
依據：`task_description/Whaleforce-AI-Coding-Test-EN.md`
方法：照 `final-reviewer-brief.zh-TW.md` 九步實際操作，另以 curl 取原始位元組交叉驗證
花費：送出 3 筆任務（1 筆免費拒絕、2 筆模型執行，合計約 USD 0.004）
穩定性：全程約 50 次請求，**0 次 502**

---

## 第一部分：逐步查證表

| 位置 | 判定 | 我實際看到什麼 |
|---|---|---|
| 步驟 1-1 | 相符 | 首次載入 0.84s，HTTP 200，Runs 表格已有 18 列，無「still starting」字樣 |
| 步驟 1-2 | 相符 | 剛好 9 顆按鈕；前 4 顆真實站、中 4 顆 fixture、末 1 顆拒絕示範，分類與說明一致 |
| 步驟 1-3 | **不相符** | 整份首頁 HTML 中 `pre-executed` 只出現 2 次，**兩次都在說明文字裡，0 列帶標籤**；`evidence captured` **0 次**。比 brief 自己記的「1 列」更差 |
| 步驟 1-4 | **部分不相符** | 說明文字已改成「find them by the badge rather than by position」（位置說法確實移除了），但標籤不存在，所以這句指示無法執行 |
| 步驟 1-5 | 相符 | 18 筆 inspect 全部 HTTP 200，涵蓋 succeeded_verified / no_result_verified / unsupported / blocked / unverified / failed / policy_refused 七種呈現 |
| 步驟 2-1 | 相符 | 未指名條目的任務：Action trace 共 2 步（`policy_check` SSRF、`note` 無記錄可配對），0 次 `navigate` |
| 步驟 2-2 | 相符 | Cost `$0.000000`，Tokens 0 in / 0 out，Model calls 0 |
| 步驟 2-3 | 相符 | 說明含「Name a URL or a site — for example "on example.org, …"」，可行動 |
| 步驟 2-4 | 相符 | Frozen postcondition 明寫「No postcondition was frozen — this run stopped before a plan was selected.」 |
| 步驟 2-5 | **不相符（文件）** | 見第二部分 N8：我實測中文承諾層任務得到 `T-DECLARED` + `succeeded_verified` |
| 步驟 3-1 | 相符 | `/support` 四列 OP-4/5/6/7，狀態全為 `implemented (M5)`，無「declared, not reachable」 |
| 步驟 3-2 | 相符 | 首頁既有紀錄顯示該按鈕落 `T-EXPERIMENTAL` / `unsupported` / `policy_refused`，2 步 0 元 |
| 步驟 3-4 | **無法判斷** | 整個部署 20 筆執行中，找不到任何一筆成功展示 OP-5（展開摺疊區塊）。詳見 N3 |
| 步驟 4-1 | 相符 | 順序正確：`policy_check`(SSRF) → `note`(執行路徑) → `note`(postcondition frozen，附 hash) → `policy_check`(目標 URL robots) → `navigate` |
| 步驟 4-2 | 相符 | `policy_check` detail 列出 6 個解析到的 IP（v4+v6）與完整 robots 判定物件，非空 |
| 步驟 4-3 | 相符 | 「0 retries · 0 recoveries」兩數分開列，並附「只有第二個算自我修正」的定義 |
| 步驟 4-4 | 相符 | 我送出的承諾層任務：進度即時推進（Step 5 → Step 7 → …），約 8 秒轉為終局狀態，**未卡住**，console 無任何訊息。已知問題 1 的反向查證通過 |
| 步驟 4-5 | 相符 | `budget_exhausted` 那筆 Steps 25 of 25，Claims 面板「No claim was produced.」 |
| 步驟 5-1 | 相符 | Artifact 行為「`art_76e3a69b2614` · captured 2026-07-29 · sha256 `59900c813698d780…`」 |
| 步驟 5-2 | 相符 | 存檔位元組中兩段字串都找得到；counter 確實跨行（`0 results for` \n `"a term that appears on no page".`） |
| 步驟 5-3 | 相符 | 自算 sha256 = `59900c813698d7806f02884c939e646a70608e6ef7176474fb3a86e48e3ca9e5`，與頁面前綴一致；長度 3,230 bytes，與 brief 記錄的**另一個 id** 同雜湊 → 內容定址宣稱成立 |
| 步驟 5-4 | 相符 | `items` 顯示為 not verified + `locator_not_found`，並附「值可能在頁面上，但無法從宣告的標籤走到」的說明，未被隱藏 |
| 步驟 5-5 | 相符 | 藍框內明印「It does **not** mean the claim is true in the world.」 |
| 步驟 5-6 | 相符 | 7 道閘門全 pass，含 `postcondition_frozen`（事前凍結）與 `absence_mode_a`，每道可展開 |
| 步驟 5-7 | 相符 | 「2 of 3 claims were independently re-resolved…Not re-resolved: items」與面板上的 3 個宣稱、2 個 verified 完全對得上 |
| 步驟 5-8 | 相符 | GICS 那筆存檔 **1,937,772 bytes**，sha256 `4b5fe2bbd151236c…` 自算一致；字面 `GICS Sector` 在位元組中 **0 次**（被標籤切開），`AES Corporation` 與 `Independent Power Producers` 各 2 次；另找到 `headerSortDown` 1 次 → **排序狀態確實可從存檔位元組獨立讀出**，驗證鏈是真的 |
| 步驟 6-1 | 相符 | 詳情頁實際 9 塊面板；grader-guide 只列 7 塊，且完全沒提 Locator memory |
| 步驟 6-2 | **無法判斷** | 20 筆執行中 0 筆出現 `Reportable` 欄位，無法確認該機制會顯示 |
| 步驟 6-3 | **相符（brief 的記載已過期）** | **找到 1 筆**：MDN 那題掛著紅色 `not a clean unsupported` 徽章並附說明。brief 說「一筆都沒找到」現在不成立，這個機制在部署上有活實例 |
| 步驟 6-4 | 相符 | `/healthz`：`rows_stored: 6`，`hits`/`uses`/`heals`/`quarantined` 全 0，且 `reading` 欄用整段文字解釋「有存、沒被查詢是預期讀數」。詳情頁的敘述與之一致，不會讓人誤以為它正在發揮作用 |
| 步驟 6-5 | 相符 | trace 內 artifact 連結回傳完整位元組（HTTP 200，長度與表格相符） |
| 步驟 6-6 | **無法判斷** | 20 筆執行的 Evidence artifacts 表**沒有任何 `expired` 列**，但 `/healthz` 顯示 `artifacts_expired: 3` → 該宣稱在 UI 上無法查證 |
| 步驟 7-1 | 相符 | 逐列比對，無任何一列的 Counts as success 與狀態對照表衝突 |
| 步驟 7-2 | 相符 | 全站觀察到 6 種狀態（缺 `partial`），全部落在宣告的七種內，未出現第八種 |
| 步驟 7-3 | 相符 | `/coverage` 第二張表數到 **18 列** |
| 步驟 7-4 | 相符 | 頁尾那句仍在，且與對照表一致 |
| 步驟 8-1（L-1） | 相符 | `unsupported` / `policy_refused` |
| 步驟 8-1（L-1 補救版） | **不相符** | 公告寫「ending `failed / budget_exhausted`」，實測是 **`failed` / `verification_mismatch`**（Steps 25/25）。理由段落的敘述與 trace 相符，但結論標籤錯 |
| 步驟 8-1（L-2～L-7） | 相符 | 六條全部照公告重現 |
| 步驟 8-2 | **不相符** | detail 確實引出規則原文（`Disallow: /wiki/Special:`、`group_user_agent: *`、`evaluated_path`），但 `source` 的值是 **`"matched"`**，不是 grader-guide 寫的 `"rule"`。照文件找字串會找不到 |
| 步驟 8-3 | 部分有用 | 「The list is executable」有寫，並附指令；對不跑指令的評分者只是一句宣稱 |
| 步驟 8-4 | 已完成 | 我做的逐條比對即為那次未重跑的檢查：**7 條中 1 條（L-1 補救版的 failure_class）不重現** |
| 步驟 9-1 | 相符 | `injection_detected` 為黃色 `not built`、`Due at` 是破折號、值旁附理由、不在頁首逾期清單內。理由對外部讀者夠清楚 |
| 步驟 9-2 | 相符 | 涵蓋頁「Current milestone M5」與首頁橫幅「M5 —」一致 |
| 步驟 9-3 | **無法判斷** | `Observed from` 欄**沒有任何一列**標成 regression suite，全部是「a run of the product」。區分寫在圖例裡但未被使用 |
| 步驟 9-4 | **不相符（文件）** | 生效政策是 `public_demo_funded`（free + paid 皆可用），`cumulative_billed_usd: 0`、`cumulative_notional_usd: 0.067329`、日上限 0.5 / 累計上限 2.0。`provider_spend.meaning` 有解釋 billed vs notional，但**grader-guide 從頭到尾沒提 0.1515 與 0 的落差**。評分者對照兩個數字時沒有任何東西接住他 |
| 步驟 9-5 | 相符 | `write_probe` 含 `mounted: true`、`writable: true`、`checked_at` 時間戳、`error: null` |
| 步驟 9-6 | 相符 | `unhealthy_because: []` |

另外查證：`pytest --collect-only` 收到 **618** 個測試，與文件一致；部署的 `git_sha` 就是本機 HEAD。

---

## 第二部分：已知問題清單上沒有的發現

### N1 —— 首頁的 `pre-executed` 標籤不存在，而且沒有備援路徑（高）

- **現象**：首頁 Runs 表格 0 列帶 `pre-executed` 標籤、0 列顯示證據擷取日期。同一段說明卻寫「find them by the badge rather than by position」以及「each one shows the date its evidence was captured」。
- **重現**：開首頁，在整頁原始碼搜 `pre-executed`（只會命中兩處說明文字）與 `evidence captured`（0 次）。
- **成因看得出來**：表格宣告「One row per distinct task, newest kept」。fixture 示範任務一旦被真人重跑，示範列就被同名的新列覆蓋掉，標籤跟著消失。逃生口是同段文字寫的「Every run is still listed at `/api/runs`」——**`GET /api/runs` 回 HTTP 405 Method Not Allowed**，而詳情頁的「all runs」連結指回首頁（也就是那張去重過的表）。所以評分者沒有任何路徑看到完整清單或那些示範列。
- **為什麼是問題**：`analysis-report.md` 第 448 行把這件事寫成已修的第 15 個缺陷，理由是「the rows had carried a `pre-executed` badge all along，改成用標籤描述」。那個修法在部署上不成立。這是同一族的第四個實例——**用自己的話描述自己的頁面，而沒有東西在檢查那些話**——而且一樣朝對自己有利的方向過期（宣稱「示範會標日期」＝比實際更誠實）。
- **嚴重度**：高。

### N2 —— `docs/user-guide.zh-TW.md` 把已知會被拒的任務列為「應該成功」（高）

- **現象**：§4(a)「應該成功的 — 四筆承諾記錄」列出 `Expand the collapsed navbox on that article and tell me its Energy group`，預期 `T-DECLARED` + `succeeded_verified` + `Counts as success: yes`。實際是 `T-EXPERIMENTAL` / `unsupported` / `policy_refused`。
- **重現**：首頁 Runs 表格該列，或照抄送出（免費）。
- **為什麼是問題**：已知問題 2 只承認「按鈕位置錯、行為對」。但文件把它寫成預期成功，等於一份操作手冊在教評分者去踩一個保證失敗的步驟，並在他看到失敗時無法分辨是文件錯還是系統錯。
- **嚴重度**：高。

### N3 —— 四項承諾中的 OP-5，在部署上沒有任何可查證的成功實例（高）

- **現象**：整個線上系統（20 筆執行）找不到一筆展示「展開摺疊區塊」的成功執行；首頁唯一展示它的按鈕必定被拒；grader-guide 步驟 3 的表列了它，但沒給任何一句可以貼上去的任務原文。
- **為什麼是問題**：評分者能自行驗證的承諾只有 3/4。這一項的正確性文件也承認沒有獨立 oracle，兩者疊加之後，OP-5 對外只剩一句宣告。
- **嚴重度**：高（相對於「承諾寫成網站 × 操作」這個核心賣點）。

### N4 —— `/support` 限制表 L-1 補救版的失敗原因與實測不同（中）

- **現象**：公告 `failed / budget_exhausted`，實測 `failed / verification_mismatch`。
- **重現**：`/support` 找 L-1 的「Also run with this entry」段，對照首頁同名任務那列。
- **為什麼是問題**：已知問題 3 宣稱重跑後「七條全部照公布的樣子重現，沒有一條需要改」。這條沒有。而限制清單的全部價值就是「可被推翻」，被推翻卻沒被更新，等於它現在在示範自己反對的東西。
- **嚴重度**：中。

### N5 —— 入口文件教評分者找一個不存在的欄位值（中）

- **現象**：`docs/grader-guide.zh-TW.md` L315-316 教人分辨 `source: "rule"` 與 `source: "unfetchable"`。實際欄位值是 **`source: "matched"`**。`docs/user-guide.zh-TW.md` L254 寫的是對的。
- **為什麼是問題**：這是文件自己說「區分兩種拒絕的唯一憑據」。入口文件錯、次要文件對，評分者只讀入口文件就找不到。
- **嚴重度**：中。

### N6 —— `/coverage` 對自己的兩句自述與可觀察狀態相反（中）

- **現象**：該頁寫「This counts this deployment since its last restart」與「Storage here is ephemeral, so a redeploy resets this table」。但 `/healthz` 的 `uptime_seconds` 是 476（約 8 分鐘）、`restart_count: 0`、首頁「Runs this generation 0」，而涵蓋頁列出 67 筆結果，且每一列的 `First run` id 都不在現行 Runs 表格裡。存檔本身也在持久化 volume 上（`on_mounted_volume: true`）。
- **為什麼是問題**：評分者依這句話會以為那份逾期清單短是因為剛重啟——實際上它是跨部署累計的，兩種讀法對「這條路徑到底有沒有被走過」的結論完全不同。
- **嚴重度**：中。

### N7 —— 入口文件完全沒有花費與配額提醒（中）

- **現象**：`grader-guide` 從頭到尾沒說一筆執行要多少錢、多久、以及撞到上限會看到什麼。`/healthz` 顯示 `ceiling_usd_per_day: 0.5`；`user-guide` §7 另提到每 session 10 次配額。
- **為什麼是問題**：評分者被鼓勵「用自己的題目測」，連送十幾筆很可能拿到 `blocked / queue_full`、`blocked / session_quota` 或 `blocked / provider_quota`。這些是設計行為，但沒有預告的話會被讀成系統壞掉——而且會發生在他心裡打分的那一刻。`final-reviewer-brief` 有完整的花錢警告，grader-guide 沒有。
- **嚴重度**：中。

### N8 —— 中文能力被自己的文件低估，三份文件三種說法（中）

- **現象**：我送出 `在維基百科的 List of S&P 500 companies 條目上，把成分股表格依 GICS Sector 遞減排序，並告訴我第一列` → **`T-DECLARED` + `succeeded_verified`**，2/2 claims verified，答案與英文版一致（AES Corporation / Utilities）。
  - `grader-guide` L79：「中文任務……能力面沒有做」
  - `user-guide` L93：「中文問題最好的情況也只會掉到 experimental 層」
  - `/support`：「這四項承諾在英文和中文都到得了」
- **為什麼是問題**：三種說法互斥，而**實際能力是最好的那一種**。這是朝對自己不利方向過期，但一個評分者若剛好用中文測，會先讀到「不承諾」再看到成功，反而不知道該信哪一句。
- **嚴重度**：中。

### N9 —— 成功的執行在詳情頁沒有 `Counts as success` 標記（低）

- **現象**：失敗的執行標題列有 `does not count as success`；成功的（`succeeded_verified`、`no_result_verified`）什麼都不顯示。但兩份文件都寫「頁面上每個地方都有一個獨立的 `Counts as success` 欄位」——實際只有首頁表格有。
- **為什麼是問題**：文件叫評分者「看那一欄，不要從狀態字面推斷」，但在詳情頁上那一欄不存在，他只能從字面推斷。
- **嚴重度**：低。

### N10 —— `Run` 按鈕第一次點擊常常沒反應（低）

- **現象**：三次提交都要點 2–3 次才會送出並跳轉。
- **為什麼是問題**：可能是我的合成點擊造成的，但如果對真人也成立，評分者的第一個動作就會失敗。
- **嚴重度**：低（建議人工手點確認一次即可，不必查程式碼）。

### N11 —— 修訂條數三份文件三個數字（低）

`docs/task1-spec.md` 實際有 27 條 Amendment；`docs/grader-guide.zh-TW.md` L517 寫 26 條；`prompts/README.md` 寫 twenty-five。

---

## 第三部分：文件改寫建議

### （a）會誤導的句子

1. 原句（`grader-guide` L55）：「它們的證據是**釘住的**……所以每一筆都會顯示自己的證據是哪一天抓的。」
   → 問題：頁面上 0 列有標籤、0 列有日期。
   → 建議：先修頁面（讓示範列不被去重擠掉，或直接給日期）；在那之前改成「示範的證據是釘住的，永不淘汰（`/healthz` 的 `artifacts_pinned`）」，把不成立的那半句刪掉。

2. 原句（`grader-guide` L315）：「`source: "rule"` → 站方真的禁止」
   → 問題：實際值是 `matched`。
   → 建議改成：「`source: "matched"`，並附 `rule` / `pattern` 原文 → 站方真的禁止」。

3. 原句（`grader-guide` L318）：「那個網站**根本不發布** `robots.txt`（回 404，我們讀成不受限），所以你只可能遇到後者。」
   → 問題：兩句互斥——404 既然讀成不受限，就不會產生 `robots_disallowed`。
   → 建議照 `user-guide` L253 的寫法：「books.toscrape.com 不發布 robots.txt，正常會 404 → 允許。所以在這個站看到 `unfetchable` 通常是當下的網路問題，重跑一次通常就好。」

4. 原句（`user-guide` L135 所在的「(a) 應該成功的」區塊）：`Expand the collapsed navbox on that article and tell me its Energy group`
   → 問題：這筆保證被拒。
   → 建議：換成一句有指名條目的原文並實測過再放上；改不出來就移到 (b) 區並標明「這是已知的示範缺口」。

5. 原句（`user-guide` L93）：「中文問題最好的情況也只會掉到 experimental 層。」／（`grader-guide` L79）「能力面沒有做。」
   → 問題：與 `/support` 及實測衝突。
   → 建議兩份統一成：「四項承諾的中文措辭會被路由層認得（實測可到 `T-DECLARED` 並通過驗證）。沒有翻譯的是必須對上頁面文字的值（欄位標題、分類名稱），請照頁面拼寫。我們沒有把中文納入公布的成功率。」

6. 原句（`/support` L-1 條目）：「ending `failed / budget_exhausted`」
   → 建議改成 `failed / verification_mismatch`，或整句改成不指定 failure_class 的寫法。

7. 原句（`/coverage`）：「Storage here is ephemeral, so a redeploy resets this table.」
   → 問題：帳本明顯跨重啟存活。
   → 建議刪除該句，並把「since its last restart」改成實際的累計語意。

### （b）該補而沒補

1. 讀者讀到「數字一覽：整個開發累計實付 **USD 0.1515**」之後會去 `/healthz` 對，看到 `cumulative_billed_usd: 0`，兩份文件都沒有接住他。**建議加在「數字一覽」那一列後面一句**：「這筆來自持有付費金鑰的計分行程；公開站是另一個行程，兩邊讀不到彼此的帳本，所以 `/healthz` 上的數字不同。」

2. 沒有任何花費／配額段落。**建議加在「三十秒版本」之後三行**：拒絕型任務 0 元 0.02 秒；模型執行約 USD 0.002 / 5–15 秒；併發 2、佇列 2、每 session 10 次、日上限 0.5 美元，撞到會看到 `blocked / queue_full`、`session_quota`、`provider_quota`——**那是設計行為，不是壞掉**。

3. 步驟 3 的承諾表第二項（展開摺疊區塊）沒有給任何可貼上的原文，而首頁唯一的按鈕必定被拒。**建議加在該表下方**：一句實測可用的原文；若真的沒有，就明說「這一項在這個部署上沒有可點的示範，證據在 `eval/` 的 DEV-04」——**主動說沒有，遠好過讓評分者自己發現點不出來**。

4. 步驟 6 的面板表漏了 **Locator memory**。自我維護是被直接評分的兩項機制之一，**建議補一列**：「這個版本有沒有記憶體、記憶體的邊界是什麼，以及為什麼計數器是 0」。

5. 「不乾淨的安靜結果」徽章描述得很詳細，卻沒告訴讀者去哪裡找。**部署上正好有一筆**（MDN `Array/flat` 那題）。**建議在該段末尾直接寫出那句任務原文**，10 秒可驗；一個描述得出來卻找不到實例的機制，在讀者眼裡等於沒有。

### （c）太長 / 順序不對

1. 「還有缺陷的地方」第八點（十五個缺陷）約 13 段，其中第 11、12 與最後三個的成因在步驟 1、4、9 已各講過一次。**建議砍到 5 段**：分類一句（10 個回報巧合／2 個根本沒檢查／3 個自述過期）＋兩個最值得看的實例＋三個沒修的理由。現在的寫法讓最強的那個論點（自我檢查也會出錯）被字數稀釋掉。

2. 「數字一覽」與「還有缺陷的地方」第一節的表是同一組數字，重複一次。**留「數字一覽」即可**，第一節改為指過去。

3. 「規則一／規則二」目前埋在步驟 2 的內文裡，但那是評分者最先會踩到的兩件事。**建議提到「三十秒版本」表格內**（那張表已經有「用英文、必須指名」，但沒說明失敗長什麼樣）。

4. 步驟 9 把 `/coverage` 與 `/healthz` 合成兩大段散文，而「容易讀反的欄位」實際有三個（記憶體計數器、憑證政策、`provider_spend`）。**建議改成三點式清單**。

5. 附錄 B 把 `final-reviewer-brief.zh-TW.md` 列進「你可能想看的報告」。那是給內部審查代理的指令（86 KB、1297 行），對評分者是雜訊。**建議從評分者清單移除**。

---

## 第四部分：`final-reviewer-brief.zh-TW.md` 本身的檢討

**夠不夠清楚：夠。** 我沒有打開任何其他檔案就完成了九步操作，每一步「怎麼操作 / 應該看到什麼 / 我們宣稱的是 / 請你查證」四段結構好用，`【免費】`／`【付費】`標記和兩筆付費預算的設計直接省了錢。所有按鈕的功能我都清楚——唯二沒交代的是 Runs 表格 `Path` 欄出現 `—` 的意思（拒絕型執行沒有路徑），以及詳情頁最下方「JSON · all runs」那兩個連結（後者其實只指回首頁，見 N1）。

**過程中不順的地方，三個：**

1. **Run 按鈕要點 2–3 次**（N10）。文件沒提，我一度以為表單壞了。
2. **brief 先寫了自己的答案，而那些答案已經過期。** 第 217 行說「整張表只有一列有 `pre-executed` 標籤」——實際 0 列；步驟 6 說「不乾淨徽章我們查證時一筆都沒找到」——實際找得到。brief 每次都加了「請獨立確認，不要照抄」，但**先給結論本身就是誘導**，而且這次剛好示範了誘導的代價：照抄會抄到兩個錯的。**建議：把「我們自己查到什麼」全部改成只寫查法、不寫結論。**
3. 步驟 8 那張「公告 vs 我們實際看到」的對照表已經整理好，等於答案先發下來，逐條比對的獨立性被削掉一半。

**brief 有兩個設計 grader-guide 沒有，應該搬過去**：花錢警告與付費預算，以及「id 每次重啟會變、請用任務文字定位、雜湊才是穩定的」那段提醒。後者尤其重要——我就是靠它才知道要去比對雜湊而不是 id。

## `docs/grader-guide.zh-TW.md` 的品質評語（高強度）

**能不能讓一個人類操作者清楚知道怎麼操作：大致可以，但有四個會讓他卡住或被誤導的地方**，都已列在上面：步驟 1 的標籤不存在（N1）、步驟 3 的第二項承諾沒有可貼的原文（N3）、步驟 8 的 `source` 值是錯的（N5）、以及完全沒有花費與配額預告（N7）。四個裡有三個會讓他得到「這個系統做不到它說的事」的結論，而其中兩個其實只是文件過期。

**寫作品質本身很高**：每一步「這一步在做什麼 / 我們做得好在哪 / 還弱在哪 / 我們已經試過什麼」的四段式，是我看過最誠實的自評結構，「一個沒有被量過的承諾不是承諾」「一個無法登記某件事發生的儀器，量出來的零不是零，是沒有資訊」這類句子會讓評分者記住。**問題不在說得不好，在說得太多**：534 行、「還有缺陷的地方」占了近三分之一，而最該被看見的東西（那個 1/8、以及自己檢查機制的缺陷分類）反而被同樣密度的其他段落蓋住。建議整體壓到 350 行以內，把省下的篇幅換成上面 (b) 的五個補充——**那五個全部是「讀者現在會卡住」的地方，比再多一段自我剖析更有價值**。

---

## 第五部分：文件清理清單（獨立 subagent 以評分者視角提出，未經我二次判斷）

> 以下為該 subagent 原樣回報。我唯一補充一句中性提醒：其中建議刪除 `prompts/Final-Reviewer-Session.md`，與 `CLAUDE.md` 要求「每個 session 逐字保留 prompt 紀錄」以及作業 Common Requirements 第 4 項的 `prompts/` 規定有張力，是否刪除請自行決定。

### KEEP

| path | size | why |
|---|---|---|
| `README.md` | 50 KB / 686 L | Required deliverable, the primary read. **Flag: too long for one sitting** |
| `docs/analysis-report.md` | 54 KB / 739 L | Required deliverable (perf/cost/scale/correctness). **Flag: 739 L** |
| `docs/grader-guide.zh-TW.md` | 44 KB / 534 L | Single ZH entry point; operation walkthrough + honest weaknesses. **Flag: 534 L** |
| `docs/task1-spec.md` | 161 KB / 2548 L | The amendment trail is the strongest AI-collaboration evidence. **Flag: nobody reads this linearly — README must point at §16 only** |
| `eval/dev-set.md` | 17 KB | Eval depth is graded directly |
| `eval/experimental-set.md` | 15 KB | Cross-site generalisation split |
| `eval/test-set.md` | 8.5 KB | Scored-once held-out split |
| `eval/validation-set.md` | 8.3 KB | Held-out split |
| `eval/holdout-manifest.md` | 3.5 KB | Pre-committed hashes; makes the held-out claim checkable |
| `eval/results/README.md` | 5.8 KB | Index that makes 40 result files navigable |
| `eval/target-versions.json` | 4.4 KB | Page-version pinning; separates site drift from regression |
| `eval/bundle-sample.json` | 862 B | Pre-declared sampling rule — anti-cherry-pick evidence |
| `prompts/PM-Session.md` | 77 KB | Spec says "we will actually read them" |
| `prompts/Engineering-Session.md` | 147 KB | Same. **Flag: longest file after the spec** |
| `prompts/README.md` | 4.9 KB | Entry point into 3500 lines of log; earns its place |
| `docs/m8-quiet-failures.md` | 12 KB | Silent-failure prevention is explicitly what they look at |
| `docs/m4-fail-closed-inventory.md` | 12 KB | Two real live bugs found in controls; self-maintenance substance |
| `docs/m3-model-comparison.md` | 4.9 KB | Tight, concrete model-choice tradeoff with a price |
| `docs/spend-ledger.md` | 3.1 KB | Generated, single authoritative spend figure, 9 inbound refs |
| `eval/results/*.json` (round + coldstart + spend, 18 files) | ~330 KB | Cited by name in the analysis report |
| `eval/results/bundles/{test-e82cacb9e809-r4, dev-e82cacb9e809-r3, experimental-e82cacb9e809-r3}/` | 22 MB | Submission-build evidence bundles |
| `CLAUDE.md` | 2.7 KB | Cheap, shows the working discipline |

### DELETE

| path | size | why |
|---|---|---|
| `final-reviewer-brief.zh-TW.md` | 86 KB | Instructions to an internal review agent; explicitly not for the grader |
| `prompts/Final-Reviewer-Session.md` | 3.4 KB | Logs a session whose deliverable was never committed |
| `docs/project-report.zh-TW.md` | 55 KB | Third retelling of README + analysis report, in a third language |
| `docs/user-guide.zh-TW.md` | 21 KB | Strict subset of grader-guide steps 1–9 |
| `README.zh-TW.md` | 36 KB | Translation duplicate; EN is canonical |
| `docs/analysis-report.zh-TW.md` | 48 KB | Duplicate of a doc that must be read in EN anyway |
| `docs/task2-seam.md` | 37 KB | Contract for a task not submitted |
| `docs/m2-report.md` | 15 KB | Milestone gate memo, zero inbound refs, superseded |
| `docs/m3-report.md` | 8.5 KB | Same; the planner story is already in README §4 |
| `docs/m0-runbook-ram.md` | 3.8 KB | Operator copy-paste steps; no grader will re-run them |
| `docs/m0-runbook-reachability.md` | 4.9 KB | Same |
| `docs/m1-runbook-deploy.md` | 14 KB | Zeabur console clicking; operations residue |
| `server_environment.txt` | 9.2 KB | Raw host dump, machine noise |
| `eval/state/idle-mark.json` | 188 B | Runtime scratch state accidentally committed |
| `eval/results/mem-round1-e1d13ca.log` | 8 KB | Raw memory log, unreferenced |
| `preflight/dist/reachability-bundle.b64` | 16 KB | Base64 shipping blob for a one-off host copy |
| `deploy/m0-coldstart.yaml`, `m0-ram-measure.yaml`, `m1-build-check.yaml` | 7.9 KB | Throwaway measurement pods |
| `eval/results/limitations-{b9bccb0240af,ca837143e623,def383de1d9a}.json` | 18 KB | Near-identical automated re-checks; keep only the newest |
| `eval/results/coldstart-deploy-{0900b95-partial,9591fbd,882a16d,3825577,06ae6fb}.json` | 6.3 KB | Seven readings to justify one range; two suffice |
| `eval/results/bundles/{dev-aa1ee6c5d5eb-r2, dev-e1d13cae4926-r1, experimental-e1d13cae4926-r1}/` | **21 MB, 100+ `.bin`** | Superseded-round raw blobs; dominate clone size |

### MERGE / TRIM

| path | size | target + what to cut |
|---|---|---|
| `docs/m0-preflight-report.md` | 39 KB | → `analysis-report.md` §1. Keep RAM/headroom, rate-limit, token-cost tables; drop the six gate narratives |
| `docs/m1-report.md` | 12 KB | → `analysis-report.md` §2/§4. Keep only cold-start numbers |
| `docs/m8-credential-exposure.md` | 7.8 KB | → `analysis-report.md` §3 as one "cost discipline / key isolation" subsection |
| `docs/runbook-scored-workload.md` | 21 KB | → `analysis-report.md` §5. Keep the paragraph on why scored splits run on a separate credentialed service; drop console setup |
| `docs/task1-discovery.md` | 24 KB | → `task1-spec.md` §1. Keep the requirement→evidence matrix only |
| `docs/engineering-brief.md` | 9.9 KB | → `prompts/`. It is a prompt, not a doc |
| `docs/m4-selector-contribution.json` | 32 KB | → `preflight/results/`. Raw A/B output does not belong in `docs/` |
| `docs/m4-chrome-selectors-ab.json` | 5.9 KB | Same target, same reason |
| `preflight/results/*.json` (9 files) | 76 KB | Keep `model-comparison.json` + one RAM + one reachability reading |
| `README.md` | 50 KB | Trim in place. §6 (225 L) and §7 (122 L) are half the file; cut §6 to headline numbers + link to `eval/` |

### subagent 的整體評語

> The submission's real problem is not file count but that the same story is told five times — README, its ZH mirror, the ZH project report, the ZH grader guide, and an 86 KB ZH brief written for a robot reviewer — so a grader cannot tell which document is authoritative. Deleting the four redundant retellings and keeping one ZH orientation doc removes ~200 KB of prose without losing a single claim. The `m*` milestone reports and runbooks are honest development residue, but they were written to close internal gates, not to persuade a grader. The heaviest single win is `eval/results/bundles/`: 43 MB of committed `.bin` artifacts of which 21 MB belong to superseded rounds. After all of this, four files still exceed what a human will read end to end — the two graded deliverables need an explicit "read these three sections" pointer at the top.

---

## 對照作業評分標準的結論

作業說 A 級要有：**評測設計有深度、系統展現分層/加權取捨、效能成本擴展性分析具體、失敗模式誠實揭露、prompt 紀錄顯示高品質的 AI 協作**。

- **評測深度**：四個分割、保留題組先記錄雜湊、只跑一次不重跑、公布 1/8 並拆解成「可用性 vs 能力」——這一項明顯超過 B。
- **分層取捨**：`T-DECLARED` / `T-EXPERIMENTAL` / `T-REFUSED` 在瀏覽前決定並顯示，承諾單位是「網站 × 操作」，並主動把自建站的三項從成功率撤下——這是實質的加權，不是修辭。
- **效能／成本／擴展性**：`/healthz` 把預算、單價、記憶體回收政策、儲存餘裕、支出帳本全部攤開，數字可即時對照。我實測的一筆執行 7.7 秒 / $0.002028，與公布的中位數對得上。
- **失敗模式**：七狀態 × 十八原因封閉集合、`/coverage` 主動列出「宣告了但從未產生」的十項、`not a clean unsupported` 徽章有活實例、限制清單可執行——**這一項是整份提交最強的地方**。
- **靜默失敗防護**：核心機制（凍結後條件 → 存檔位元組重驗 → 決定性裁決）我逐位元組驗過，**是真的**：雜湊自算一致、`GICS Sector` 標籤被切開而值仍在、排序狀態可從 `headerSortDown` 獨立讀出。

**扣分不在系統，在文件對系統的描述。** 我找到的 11 個新問題裡有 8 個是「文件說了一件頁面上不成立的事」，而且**其中 4 個（N1、N2、N3、N7）會讓評分者在前十分鐘就得到「這個系統做不到它自己說的事」的印象**——偏偏這個專案整份論證的核心，就是「一個看起來合理但是錯的說法，比一個大聲的失敗嚴重得多」。它把這條標準嚴格地套在自己的執行結果上，卻沒有套在自己的操作手冊上。

**一句話總評**：這是一個把「我怎麼知道自己是對的」當成產品本身來做的系統，證據鏈經得起逐位元組查驗；但它的入口文件正在對它自己做那件它最反對的事——說一個聽起來合理、實際上頁面上不成立的說法。**那個印象不是你們想給的，而它只需要修四段文字。**
