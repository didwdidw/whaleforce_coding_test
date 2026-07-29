# 獨立驗收報告

本檔含兩輪審查。**第二輪在前（最新），第一輪原文保留在後、一字未改。**

---
---

# 第二輪審查（`git_sha` **d844a9a7e9c3**）

審查者：獨立 reviewer（read-only，使用者／評分者視角，未讀任何產品程式碼）
方法：重走 `final-reviewer-brief.zh-TW.md` 九步、逐項複驗第一輪的十一個發現、加做一次使用者體驗檢討
花費：本輪送出 7 筆任務（4 筆模型執行、3 筆零成本），約 USD 0.008
穩定性：本輪約 40 次請求，**0 次 502**；首頁首次載入 0.85 秒

## 摘要

**第一輪十一項全部被處理過，其中十項確實修好了，而且修法比我建議的更徹底**（`GET /api/runs` 真的做出來、示範列改用旗標選取而不是靠「夠新」、`/coverage` 的兩句自述改成從 store 的旗標渲染）。這一輪找不到任何一個舊問題復發。

**但補上的那一項——OP-5 的可查證實例——反而揭露了一個比原問題嚴重得多的缺陷。** 我上一輪報「OP-5 在部署上沒有任何成功實例」。這一輪有了，而且它是一個**回答了別的問題卻被標成 `succeeded_verified` 的執行**。那正是這整份提交自稱在防的那一種失敗，而且它落在承諾層、計入公布的成功率、還被指南指定為「特別值得跑一次」的那一筆。

本輪新發現六項，一高五中低。

---

## A. 第一輪十一項的複驗結果

| 第一輪編號 | 現況 | 我看到什麼 |
|---|---|---|
| N1 首頁無 `pre-executed` 標籤、`/api/runs` 回 405 | **已修** | 5 列帶標籤，其中 4 列帶 `evidence captured 2026-07-27`；沒有日期的那一列（拒絕）頁面主動說明「它沒有擷取任何證據」。`GET /api/runs` 回 200。說明文字還多寫了「這幾列是靠旗標選進來的，不是靠夠新」，正面回應了去重擠掉示範列的成因 |
| N2 user-guide 把 navbox 任務列為「應該成功」 | **已修** | 換成 `On the Wikipedia article for Apple Inc., expand the first collapsed box…`，並加了 ⚠️ 說明那顆按鈕一定會被拒 |
| N3 OP-5 無可查證實例 | **形式上已修，實質上更糟** | 首頁多了一筆 T-DECLARED / `succeeded_verified` 的 OP-5 執行。見下方 R1 |
| N4 L-1 補救版失敗原因錯 | **已修** | `/support` 現在寫 `failed / verification_mismatch`，解釋也改成實際的「驗證器讀到表格自稱未排序」，並自承「那支可執行檢查以前只比對 terminal status，看不出差別」 |
| N5 `source: "rule"` 不存在 | **已修** | 指南改成 `source: "matched"`（附 `rule` / `pattern`），且 books.toscrape 那段的自相矛盾也改掉了 |
| N6 `/coverage` 自述會歸零 | **頁面已修，文件反而過期** | 頁面現在寫「記在掛載磁碟上，跨重啟與重新部署累計，只會變短」。但指南 L377 仍寫「這一頁上有兩句自述說它會歸零」——見 R5 |
| N7 入口文件沒有花費／配額提醒 | **已修** | 「三十秒版本」後面新增一節，列出 0 元拒絕、USD 0.002 中位數、2/2 併發佇列、session 10 次、日上限 0.5，並明說撞到是宣告過的狀態不是故障 |
| N8 中文能力三份文件三種說法 | **已修** | 規則一改寫成「建議用英文，但中文不是壞掉的」，直接把我實測的那句中文任務貼上去，並說明沒被翻譯的是必須對上頁面文字的值 |
| N9 成功執行沒有 `counts as success` 徽章 | **已修** | 成功的執行標題列現在有綠色 `counts as success` |
| N10 Run 按鈕第一次點擊沒反應 | **未修，本輪三次提交全部重現** | 見 R6 |
| N11 修訂條數三個數字 | **已修** | spec 27 條、指南 27 條、`prompts/README.md` twenty-seven，一致 |

另外複驗的既有宣稱，全部仍然成立：638 個測試（`pytest --collect-only` 實數）、`/coverage` 七狀態全 produced、十八個 failure class、`injection_detected` 為 `not built` 且 `Due at` 是破折號、`write_probe` 三欄齊備、`unhealthy_because` 為空、存檔雜湊自算與頁面顯示一致（本輪再驗一份 2,523,585 bytes 的 Apple 條目存檔，`4406bc96901eecb2…` 相符）。

---

## B. 本輪新發現

### R1 —— OP-5 承諾「取出展開前看不到的值」，但它從來沒有取出任何值，而那些執行被標成 `succeeded_verified`（高）

**現象。** 我照 `eval/dev-set.md` 的 DEV-04、DEV-05 原文各送出一次：

| 任務原文（逐字） | 凍結下來的 goal | 產生的宣稱 | 結果 |
|---|---|---|---|
| `…expand the first collapsed box at the foot of the page and tell me **its title and the label of its first row group**.` | `expand collapsed box 1 and report that it is no longer collapsed.` | 只有 `still_collapsed`（`relation: element_absent`） | `T-DECLARED` `succeeded_verified` `counts as success` |
| `…expand the second collapsed box and tell me **how many entries are in its first row group**.` | `expand collapsed box 2 and report that it is no longer collapsed.` | 只有 `still_collapsed` | `T-DECLARED` `succeeded_verified` |

**兩題問的東西，一個都沒有回答。** 標題列寫的是「All 1 required claims were re-extracted… and matched the run's values」——那句話是真的，只是那「1 個 claim」不是使用者問的東西。

**答案就在存檔裡。** 我把 DEV-04 那筆的 DOM 存檔抓下來（`art_c8330f17bc11`，2,523,585 bytes，雜湊相符），裡面 `navbox-group` 的標籤是 `Products` / `Hardware` / `Mac` / `iPod` / `iPhone`。所以不是「頁面上讀不到」，是**編譯凍結條件的時候把問題的後半段丟掉了**。

**四個地方承諾的是值，不是狀態：**

- `/support`（線上）：`OP-5 · en.wikipedia.org · Expand a collapsed box and **extract a value not visible beforehand** · implemented (M5)`
- `README.md` L146：`Expand a collapsed section/navbox and **read a value not visible beforehand**` … **2 of 2**
- `docs/analysis-report.md` L275：`**OP-5** — expand a collapsed box, **read a value**`
- `eval/dev-set.md` DEV-04：postcondition `title text and first row-group label read from a snapshot taken after expansion`；expected_anchor `the first row-group label cell`；note **`what is verified is the state transition plus the value`**

唯一講出真相的是 `docs/grader-guide.zh-TW.md` L174：「那是一個對『狀態真的變過』的檢查，不是對『值長得對』的檢查」。**但它就在同一步驟裡、承諾表下方兩段**，而承諾表寫的是「讀出展開前看不到的值」。一份文件在兩段之內自打嘴巴，讀者會相信上面那張表。

**為什麼這是本輪最嚴重的一項。** 指南步驟 2 用整整一段講一個開發期的教訓：「一個要求依 CIK 遞增排序的任務，被配到依 GICS Sector 遞減排序的計畫，執行得完美無缺、回報成功……因為沒有人拿計畫去比對任務本身的字句。」**R1 是同一個缺陷的另一個實例，而且還活著**——凍結下來的 goal 與任務原文的差距，沒有任何東西在檢查。它同時：

1. 計入公布的承諾層成功率（`README` 的 OP-5「2 of 2」量的是狀態轉換，不是它宣稱量的東西）；
2. 就是這一輪為了回應我上一輪 N3 才加到首頁與指南上的那一筆；
3. 是指南裡唯一被特別標註「特別值得跑一次」的執行。

**建議（三選一，不要都做）：**
- 最誠實、最省事：把 `/support`、`README`、`analysis-report` 的 OP-5 措辭改成「展開摺疊區塊並證明狀態改變（`element_absent`）」，並在 `dev-set.md` 把 DEV-04/05 的 postcondition 改成它實際檢查的東西，同時在指南寫明「這一項驗的是狀態轉換，不是值」。承諾縮小，但它會是真的。
- 或者：把值那半真的做出來（DOM 裡有），讓承諾成立。
- **絕對不要**：維持現狀。一個 `succeeded_verified` 掛在沒回答的問題上，是這份提交唯一不能有的東西。

### R2 —— 首頁說「fixture 那幾顆按鈕就是下面預先執行用的同一批任務」，4 筆有 3 筆不是（中）

| 範例按鈕 | 對應的 pre-executed 列 | 一樣嗎 |
|---|---|---|
| `Search the fixture catalogue for lantern` | `Search the fixture catalogue for lantern` | 是 |
| `Is any product **in the fixture catalogue** priced over £100?` | `Is any product priced over £100?` | **否** |
| `Read page 2 of the **fixture** browse listing without clicking next` | `Read page 2 of the browse listing without clicking next` | **否** |
| `Dismiss the overlay on the **fixture** gated page…` | `Dismiss the overlay on the gated page…` | **否** |

看得出來這是 N1 修法的副作用：把示範任務的字串改得跟按鈕不同，去重就擠不掉它們。但那句說明沒有跟著改。**後果**：評分者點那三顆按鈕送出，會得到一列跟示範列幾乎同名、但其實是另一筆的紀錄，並以為自己重跑了示範。

### R3 —— 「示範是容器每次啟動時跑好的」不成立；而且它們來自三天前一個比現在弱的版本（中）

**現象一。** 首頁寫「Rows badged `pre-executed` were run at startup」，指南 L56/L60 寫「其中一批是**容器每次啟動時就自動跑好的**」。但這次啟動什麼都沒跑：`/healthz` 的 `uptime_seconds` 是 145、首頁「Runs this generation 0」「Restarts 0」，而示範的證據日期是 **2026-07-27**，且 `/coverage` 的 `succeeded_verified` First run 就是那筆示範（`run_505c6ac2b811`）——它跨了不知道多少次重啟都沒變。**它們是被種下一次然後釘住，不是每次開機重跑。**

**現象二，比較嚴重。** 我點開那筆示範（`run_505c6ac2b811`），它的 **What was checked 只有 4 道閘門**：`postcondition_frozen` / `artifact_available` / `artifact_source_matches_plan` / `required_actions_present`。現行版本的執行有 6～7 道，而且多一行「N of M claims were independently re-resolved」。示範裡沒有那一行，也沒有現行的 `artifact_origin_is_the_named_site`、`artifact_source_is_accounted_for_by_the_trace`、`landing_explained_from_the_plan_target`，trace 的每一步也沒有 `freshly derived` 定位來源徽章。

**評分者最先被指示去點的那幾筆，展示的是一個比現在弱的驗證器**，而頁面上沒有任何一個字說它們來自舊 build。它同時還顯示 `empty_state not verified / locator_not_found` 掛在一筆 `succeeded_verified` 上（因為那是 optional claim），沒有解釋——第一印象直接是「成功的執行裡有一個紅色的沒通過」。

**建議**：把「run at startup」改成「seeded once and pinned」，並在那幾列旁邊標上產生它們的 build。否則就重種一次，讓示範跟現行驗證器同版本。

### R4 —— Runs 表格預設把 `inspect` 整欄切在畫面外（中）

量到的數字：表格容器 `clientWidth` **922**、`scrollWidth` **1022**，`inspect` 欄右緣在 1022。**`scrollLeft` 是 0 時它完全不可見**，要在表格內橫向捲動才會出現，深色主題下沒有任何捲動提示。Task 欄只有 245px，任務文字被截到約 40 字。

**後果有兩層：**
1. 指南的第一個動作是「捲到 Runs 表格，隨便點一筆進去」。那個連結預設看不到。整頁最重要的行為召喚是隱藏的。
2. 指南步驟 8 要求把 `/support` 限制表的七條任務原文拿去和 Runs 表格逐條比對。Task 欄截斷讓這件事只能靠逐筆點開來做。

**建議**：`inspect` 改成固定在右側（`position: sticky`），或整列可點，或把 Task 欄的完整文字放進 `title` 屬性。

### R5 —— `docs/grader-guide.zh-TW.md` 內部三處互相矛盾（中）

1. **L377**：「這份帳本記在持久磁碟上，所以它是跨部署累計的……（**這一頁上有兩句自述說它會歸零，那兩句是錯的**，寫在最後一節的已知缺陷裡。）」——那兩句已經在這一版修掉了，`/coverage` 現在說的就是跨部署累計。而同一份文件的第九節（L493）也寫著它們「現在也修完了」。**指南同時說一個缺陷還在、和它已經修好。**
2. **prompts 的數量**：L24 寫「三個工作階段」，L556 與 L584 寫「兩個」。而 `prompts/README.md` 開頭仍寫 "Two logs"、表格只列 `PM-Session.md` 與 `Engineering-Session.md`，完全沒有 `Final-Reviewer-Session.md`。`prompts/` 是被直接評分的交付物，它的索引漏掉了三分之一的內容。
3. **L25**：說 `acceptance-report.md`「**第九節**是我們對它的回應」。acceptance-report.md 沒有第九節；第九節在指南自己裡面。L567 講對了，但兩句不一致。

這三項都很小，但它們是同一族的第 21、22、23 個實例——**用自己的話描述自己，而沒有東西在檢查那些話**。指南 L495 剛寫下修法通則：「測試要拿渲染出來的頁面去比對程式碼推導出來的值，不能比對那句話本身。」這三處正好是那條規則管不到的地方：文件對文件、文件對自己。

### R6 —— Run 按鈕第一次點擊沒反應（低，與第一輪 N10 相同）

本輪三次表單提交（英文承諾層、中文承諾層、L-2 長任務）**全部要點兩次以上**才會送出並跳頁。可能仍是我的合成點擊造成的，但兩輪六次全中，值得有人用真的滑鼠點一次確認。

---

## C. 使用者體驗檢討

### 執行中的頁面：資訊其實夠，但只有一行在動

我在瀏覽器裡送出一筆 25 步的任務並全程盯著。實際狀況比我預期的好：**首次載入時，Action trace 已經渲染到當下那一步**，Timing 寫「Execution: **still running**」，Budget 寫「Steps **2 of 25**」。這比大多數同類介面都好。

問題是**之後只有標題那一行會即時前進**，下面的面板停在載入當下的快照。所以會出現：標題已經跑到 `Step 11`，而 Budget 面板還寫著 `Steps 2 of 25`。兩個數字同時在畫面上、互相矛盾、都沒有標「這個會動、那個不會」。

**四個具體的困惑點：**

1. **`No claim was produced.`** 這句話在執行中就出現在 Claims 面板裡。它讀起來是結論（「這次沒有產出任何宣稱」），實際意思是「還沒有」。建議執行中改成 `No claim yet — the run is still going.`
2. **`Step 11: Snapshot captured: step-2`** ——同一行有兩個 "step"，意思不同（前者是執行步數，後者是規劃步驟的名字）。我看了兩次才確定不是頁面壞了。建議把 artifact 的內部名稱從進度行拿掉。
3. **進度行沒有經過時間，也沒有把 25 步預算搬上來。** 這個系統最有辨識度的行為就是 fail-closed 的步數上限——我那筆跑了 17 秒、25 步、最後 `budget_exhausted`，**全程沒有任何地方告訴我它正在接近上限**。建議標題行改成 `Step 11 / 25 · 8s`：多兩個字，就把「它在幹嘛」和「它快撐不住了」一起講掉了。
4. **`Waiting…`** 是送出後的第一個狀態，沒有說在等什麼（佇列？瀏覽器？模型？）。這正好是你問的那種情況：pending 但沒說在幹嘛。建議至少分成「waiting for a browser context」和「waiting on the model」。

（一個要補的誠實說明：我沒能看到 `queued` 的畫面，因為併發從未被填滿。文件說滿了會回 429 + `Retry-After`，但**佇列位置在頁面上有沒有被展示，我無法查證**。）

### 首頁：三個會讓第一次來的人卡住的地方

1. **`inspect` 看不見**（R4）。這是最嚴重的一個，因為它擋住的是指南要求的第一個動作。
2. **`Runs this generation 0` 就擺在一張有 20 筆紀錄的表格上方。** 它指的是「這個瀏覽器世代」，但旁邊沒有一個字解釋，讀起來像計數器壞了。
3. **導覽列四個連結沒有任何說明文字。** `Status coverage` 對第一次來的人不知道是什麼；`Health` 點進去是一大坨 JSON，沒有任何導讀。指南裡有解釋，但**頁面本身不能假設讀者手上有指南**——真正的評分者很可能先點頁面、後讀文件。

### `/support`：內容是全站最好的，位置最差

「Known limitations you can reproduce」那張表是這份提交最有說服力的東西——七條可貼、可跑、可推翻。但它前面壓著六段密集散文（承諾表、語言、fixture 說明、breadth 取捨、機制證據、mutation seed 表），要捲很久才看得到。**建議把限制表移到 `/support` 的最上面**，承諾表跟在後面。一個評分者在這頁上最想做的事是「找一個我可以打進去看它壞掉的東西」，那應該是第一屏。

### 整體：評分者知道自己每一步在幹嘛嗎？

**照著指南走，知道。單看網站，一半。** 網站上每個面板都有解釋自己的段落，寫得很好；但沒有任何一個地方告訴你**這一頁在整個流程裡的位置**，也沒有「下一步做什麼」。四頁之間沒有任何引導性的連結（例如首頁的失敗列直接連到 `/support` 對應的那一條限制、`/coverage` 的 `overdue` 列直接說「你可以這樣觸發它」——後者其實有寫在散文裡，但沒做成連結）。

**成本最低、效果最大的一項改動**：在首頁最上方那條黃色橫幅下面加三行「你可以做的三件事」，各附連結——(1) 點一筆已經跑完的紀錄看證據長什麼樣；(2) 貼一個任務進去（附一句花費與耗時）；(3) 去 `/support` 找一條我們自己承認會失敗的任務打進來。現在那條橫幅講的是 M5 的里程碑狀態，那是**開發者關心的事，不是第一次來的人關心的事**。

---

## D. `docs/grader-guide.zh-TW.md` 的品質評語（第二輪）

**比上一版明顯好。** 我上一輪指出的四個「會讓評分者卡住或被誤導」的地方（標籤不存在、OP-5 沒有可貼原文、`source` 值寫錯、沒有花費提醒）全部處理了，而且新增的第九節把整件事寫成公開紀錄，這一節本身就是這份提交最強的一段：**它示範了自己主張的那套標準被套用在自己身上時的樣子。**

**但它從 534 行長到 599 行，而我上一輪的建議是壓到 350 行以內。** 每一次審查都在往上加，沒有任何一次在往下砍。現在的問題不是內容不好，是**分量分配和論點強度反過來**：

- 「還有缺陷的地方」第八、九節加起來約 30 段，占全文近四分之一。第九節裡有一半的內容（第 11、12 個缺陷、三個自述過期的缺陷）在第八節已經講過一次。**建議第八節只留分類與那句「一個前提沒有被量過的修法不是修法」，實例全部併進第九節。**
- 第九節寫得很動人，但它是**關於流程的**。一個評分者要判斷的是系統，不是流程。現在的比例會讓人覺得這份提交最想被稱讚的是「我們很誠實」——而誠實不是評分項，**評測深度、分層取捨、成本分析、失敗模式揭露**才是。那四項這份文件都有，但都比第九節短。
- L1–L50（讀哪些東西 + 三十秒版本 + 花費）現在是全文最有用的一塊，**但它排在「先講結論」後面**。建議把三十秒版本與花費提到最前面，「先講結論」那三段併進去。

**還有一個結構問題我上一輪沒說：這份文件同時是操作手冊和說明報告，而這兩件事的讀者速度差十倍。** 一個要動手操作的人需要的是「貼這個、看那裡」；一個要理解設計的人需要的是那四段式論證。現在它們交錯出現，操作者要跳過大段論證才能找到下一個動作。**如果只能改一件事，我會把每一步的操作指令抽出來，做成文件最前面的一張「九步、九個動作」的表，論證留在原地。** 一個人可以三分鐘操完，再回頭讀他有興趣的那幾步。

---

## E. 對照評分標準的結論（第二輪）

上一輪我說：「扣分不在系統，在文件對系統的描述。」**這一輪要修正這句話。**

文件那一層確實補好了——十一項處理了十項，而且修法比我建議的更徹底。但這一輪在系統本身找到了一個上一輪看不到的東西：**OP-5 的 `succeeded_verified` 掛在一個沒有回答的問題上**（R1）。那不是描述的問題，是產品的問題，而且它剛好落在這份提交唯一不能出錯的地方。

它的存在方式很值得注意：**它是因為我上一輪要求「給我一個 OP-5 的可查證實例」才被暴露出來的。** 在那之前，OP-5 的 2/2 只存在於評測結果檔裡，沒有人能點開它。這件事本身就是這份提交的核心論點的一次現場演示——**一個無法被點開的通過，和一個通過長得一模一樣**——只是這次示範的對象是他們自己。

其餘的評分面沒有變，而且都經得起查：證據鏈我兩輪各自逐位元組驗過（雜湊自算相符、標籤被標籤切開而值仍在、排序狀態可從 `headerSortDown` 獨立讀出）；七狀態十八原因封閉集合；`/coverage` 主動列出十項從未產生的失敗原因；限制清單可執行且這次真的被更新過。

**一句話總評（第二輪）**：這是一個把「我怎麼知道自己是對的」當成產品來做的系統，而它現在的最大風險不是不夠誠實，是**誠實的密度掩蓋了一個真的缺陷**——四項承諾裡有一項，長期以來一直在為一個它沒有回答的問題發出成功徽章，而三份文件、一份評測規格和一個線上頁面都在替它背書。**先修那一項，再考慮把文件砍短。**

---
---

# 第一輪審查（原文保留，未修改）

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
