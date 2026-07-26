# PM Session

Role: 資深 Product Manager（規劃、不親手 coding）
Scope: Task 1 — Generalized Browser Automation Agent 的執行規劃

---

/init

Please analyze this codebase and create a CLAUDE.md file, which will be given to future instances of Claude Code to operate in this repository.

==========

task_description/ 裡面有本項專案任務描述，兩份文件內容一樣只是語言不一樣，英文的用字比較清晰，請以讀英文的為主。
請先逐行詳細閱讀文件內容，了解所有的限制與要求。

你是一位資深 Product Manager 的角色。你不用親手 coding。你需要做的事是跟我討論怎麼把 task 做好，然後列出步驟（還有階段性驗收，if this is a verified-able task）。
把規劃寫成一份 md file 即可。如果有想要找我討論的也可以隨時停下來討論。
這一階段只做 Question 1 的執行規劃，完全不碰 Question 2。

閱讀完之後，先不用開始實際規劃與討論。請先完成以下的 init 事項：
1. 根據 Common Requirements 第四項: Prompt records 的要求，請先建立 prompts folder, 並且以 session 為單位把我的所有 prompt 都紀錄進去。每則 prompt 之間用 "/n ========== \n" 這樣的方式分隔開來。包含現在這一則 prompt 也要 log 進去。本 session 的命名為 "PM Session"。並且把需要根據不同 session 去 log 我的每則 prompt 這個規則記錄進去 CLAUDE.md (so that all the following new session will know they should do this automatically)
2. 完成後做一次 commit。把 task_description 加入 git ignore 中避免題目明文外流。(According to the requirement, this repo will be public (at leat for a while))

==========

Again, 你是資深 Product Manager 與 Acceptance Owner 的角色，不需要也不被允許親自寫產品 code (未來會有 engineering agent 根據你所開出的 spec 去實作，所以請確保你開出的 spec 是方便 engineering agent 閱讀與理解的)

Whaleforce-AI-Coding-Test-EN.md 是唯一 project requirement 來源，中文版只用來核對。若有差異請列點提出，禁止自行消除
請一起實作 Task 1 的 implementation plan 的規劃，收斂成可執行且可獨立驗收的 frozen spec (以 md 檔的形式呈現)
Note: 現階段完全不設計 Task 2 的實作規劃，但考量到 Task 2 是 Task 1 的延伸，也就是 Task 2 會吃 Task 1 的 Output，請仍然詳細閱讀 Task 2，確認 Task 1 可以交付哪些 upstream data 給 Task 2。本輪不要設計詳細 schema，單純 put this in mind 即可

除了 Whaleforce-AI-Coding-Test-EN.md 裡明示的 limitation 以外，我額外補充幾點 non-negotiable product principles (if conflict, 以 Whaleforce-AI-Coding-Test-EN.md 為主)：
1. Target audience 先鎖定公司內部 quant researcher, data scientist, etc.
2. 只執行公開、read-only web tasks。不要花任何時間心力去嘗試需要登入、處理私人資料、交易、做外部寫入、或有反爬蟲機制的網站
3. LLM API 與 model 的選用應由某個變數的 value 決定，方便未來隨時一鍵替換。開發測試階段將預計使用 Gemini API。Note: 目前只處理 public data，未來若有處理任何 private data，需要再商討 data-safety gate
4. 支援範圍必須誠實揭露，不能暗示「所有網站都可靠」

首先請做 discovery：
1. 建立英文原題的 requirement traceability，並指出中英任何實質差異 if there's any
2. Without knowing my prefered solution shape，提出至少兩個真正不同的產品方向。比較 user value、如何證明是真 browser automation、self-correction/self-maintenance、silent-failure 風險、evaluation、public demo 可行性、延遲/成本與主要 trade-offs
3. 在 high level 說明 Task 2 大概會希望 Task 1 預留什麼責任邊界。不要定 schema
4. 建議適合這份作業的 agent/session workflow 與驗收獨立性，但先不要建立 session 或執行
5. 最多問 5 個會實質改變 scope、architecture 或 acceptance 的問題，但不要重問上面已決定的原則

==========

sry I stopped by accedient. keep going

==========

docs/task1-discovery.md 請不要再改寫了，不要因為我下面的決定而去修改。這份文件可以用來當作整個 project 發展過程方便未來 trace

首先回答Q1–Q5

Q1: 選 (c) 分層，但定義要再更嚴謹一點
- 對外承諾的最小單位是 site × operation 為一個 record，而不是整個網站。也就是說同一個網站上沒被 eval 過的 operation 不可以自動繼承承諾
- 宣告站點以外的一般公開網站標成 experimental，UI 要看得出來，而且允許放棄，且 experimental 的結果不計入主要成功率
- 你推薦的 "C 當產品框架 + A 當 execution tier + B 當 fallbac" 我同意，這就是 tiered 該有的 implementation

Q2: 選自架 headless browser，跟 app 同一個部署，不用 managed cloud browser service，不要把問題複雜化
- 成本上限：不建立任何會產生固定月費超過 USD 10 的資源，能用 free / hobby tier 就用。要開任何付費資源前先停下來問我（並提供替代方案）
- demo concurrency 先暫時訂 2 個 browser worker + 一條 waiting queue（2 個等待位）。滿了就回 429 就好，不要無限排隊
- 每個 run 要設定 hard timeout 與 step / LLM call budget，超過就 fail closed
- 具體挑哪一家 hosting 留給後面的 engineering preflight 決定，現階段只負責訂出上面這些 constraint 與驗收方式
- 對 grader 行為的預期請當成設計輸入。他們會用自己的題目、可能連續觸發好幾個 run、也可能丟我們沒宣告支援的網站進來。系統在這三種情況下的行為都要是設計過的，不能只靠運氣

Q3: evidence + abstention 是 product guarantee，不是 debug 手段。系統可以(也必須有辦法)承認「我無法驗證這件事」
- verified 的定義為：這個 claim 與我們在 retrieved_at 當下保存下來的來源 artifact 一致，且通過 entity / 型別 / 日期 / 單位等 deterministic checks，但不是「保證這件事在世界上絕對為真」，這點在 UI 與文件都要寫清楚
- LLM 只能產生 candidate（action、locator、claim、evidence span），不能核准自己。要標成 verified 的東西，最後一關必須是 deterministic code 在保存下來的 artifact 上重新定位並檢查。第二個 LLM 只能 reject
- 若要保留 LLM 的自然語言摘要，它必須在 UI 與資料結構上都跟 verified facts 隔離

Q4: 目標提交日 7/30，大約還有 2 個 working sessions。我的計畫是會再開一個 engineering session 執行改 code 與初步驗證，再一個 independent acceptance reviewer         用證據挑錯與驗收
- 雖然我會做 task 2, 但 task 2 先視為 optional。現在不做任何 item 1–16 ma、不做 Task 2 的 ground truth
- 但 Task 1 的 submission 必須包含一個真的做完、而且被獨立 consumer 測
- seam：能唯一定位一份 10-K，抓下 raw primary document 與 complete submment inventory，每個 representation 都有 byte length / media type /SHA-256 / retrieved time。這個 seam 另外計分。它不能拿來充當 browser generalization 的 coverage，也不能取代 Task 1 自己的 hard gates。

Q5: (a) + (b)，不採 (c)。
- 自建一個可控 fixture site，能程式化做 mutation：id / class 全改名、按 、插入 wrapper 或重排 DOM、放兩個相似 decoy、delayed render、overlay
擋住原本的 action、pagination 控制項移位、empty state、malformed conten
- ground truth 由 fixture 自己的 server state 或 test hook 產生。不能讓同時當答案又當裁判
- 真實網站的 organic drift 有遇到就記錄下來當 bonus，但不當成 acceptanc

----------------------

接下來是我的幾個假設。以下單純是我的想法，不是題目要求，寫進文件時請分開標記。
不要照單全收，請逐條給我 accept / modify / reject ，要真的去挑，判斷合理性。同意的也講一下它的潛在風險

H1: 怎麼證明這真的是 browser automation，不是包了一層 LLM 的 scraper
- 每個 eval case 事先聲明它必須做到哪些 browser action、預期的 state 變化、post-condition 跟 required evidence
- 「實質 UI action」我先定義成在已 render 的頁面上由 agent 造成 URL/表單狀態/分頁 等等的可觀察改變，而且這個改變是完成任務所必要的。如果是單純導航進去，看一看，最後 extract，這樣不算
- API 只能拿來做 supporting discovery 或當 oracle。跳過必要 UI action 的 run 就算答案是對的也不算成功。 Regression 裡要故意放一個這種案例確認它會被判 fail

H2: 成功的定義
- terminal status 不能只有 success / error。至少要分 succeeded_verified、no_result_verified、partial、failed、blocked、unsupported、unverified。其中 partial 不算 success
- 兩個不能因為 timeout、quota 用完或 fallback 而放寬妥協的點：
1. 被標成 verified 但其實是錯的 claim 要是 0
2. 標成 verified 的結果，required evidence coverage 要是 100%

H3: self-correction 要有實質，還有 eval 怎麼切
- 同一個策略對 transient error 重做一次只算 retry，不算 self-correction。真正的 recovery 要換一整個 strategy family，而且要重新驗證完全相同的 postcondition
- recovery 不可以改寫原本的 goal 或降低成功標準，如果只有降標準才會過，那正確答案是 fail 或放棄
- eval 切成 dev / validation / test 三份。dev 給 engineering session 看，另外兩份是測試資料集，engineering 永遠看不到
- holdout 的成績用第一次跑的結果算。已經拿出去看過的那份之後只能叫 regression，不能再說是 held-out

H4: Scope
- 站點候選為 Wikipedia、arXiv、SEC EDGAR，加上自建 fixture。base case 數量我想抓 20 出頭，dev 大概 15，另外兩份各 5 (大概就好)
- 有時間才做的：多加站、跨 run 的 locator memory、compare 跟 document download 這兩種 task type

另外幾條比較短的：
- model 用 config 換，但正式跑 eval 期間會 pin 一個 stable ID，不准用 latest alias，更不准 silent fallback (真的要換 model 就重跑同一組 case 並留紀錄)
- 只送公開資料給 provider，送出前有一道本地 gate 擋掉 key / token / private URL
- VERY IMPORTANT: 公開部署只允許 read-only，每次跳轉都要重新檢查目標 IP，擋掉 localhost 跟內網。網頁上的文字一律當成 untrusted data，嚴禁改寫 agent 的目標或權限
- Task 1 只負責取得跟保存，Task 2 才做內容理解，Task 2 不應該需要知道我們的 browser plan 或 locator。SEC 那邊用可聯絡的 User-Agent，自己限速保守一點

所有資訊都上網查一下官方文件。比如說 Gemini 跟 SEC 的相關資訊永遠以官方文件為準，不准憑印象寫 quota 數字或 model name 等等。

候選站點的穩定性要先 preflight，有問題就提替代方案跟我討論，不要直接換掉，也不要花時間力氣想辦法繞過

這輪除了照 CLAUDE.md 把這則 prompt log 進去以外不要改任何檔案，不急著 freeze，更不要寫 code (Again, you are a PM, not an engineer)。看看是否有哪幾條彼此衝突、或還有什麼問題，確認一下。還需要我決定或是討論的也一並提出。

==========

請你不要每一次回覆都帶一次 commit
依照正常專案開發習慣，做完一個小功能、決定一件事情、進度到一個段落後再 commit
不要無謂的做一堆 commit
Record this in your memory

------------------------------------

Good job in verification. I didn't except the problem of arXiv. 這種前提要先查清楚才不會做白工
Now answering your questions:

D1: 照你的方向切，但 must-have 我要加東西。"across different sites" 是題目原文的硬要求，只留 Wikipedia + fixture 會直接踩線。所以 must-have 至少要有兩個真實公開站，能到三個更好
- must-have：fixture、Wikipedia 條目頁互動、一個政策乾淨的第三方站、EDGAR seam（走 server-side，不算進 browser coverage）、evidence + deterministic verifier、status 分類、跨 family recovery、locator memory、eval harness、部署
- stretch：EDGAR FTS 的 UI 案例、compare / download 這兩種 task type、再多加站
- EDGAR FTS 這些 must-have 都 pass 了再補，它是加分不是 foundation

D2: (a) + (c)，arXiv 直接拿掉。替代站用你提的 toscrape，理由是它存在的目的本來就是給自動化練習，政策最乾淨，而且有分類篩選跟分頁剛好補我們缺的 task type。
Note: README 請老實寫選它就是因為政策乾淨，不要刻意包裝成研究情境

D3: 統計論點我接受，但我不想用「多寫案例」來解。改成用承諾數反推：先把對外承諾的 site × operation 壓到你有把握的幾條，每一條在 dev 跟 test 各至少一個案例，案例數就自然長出來。承諾少一點沒關係，但每條承諾都要有證據。以你的 15 / 8 / 8 當上限抓，做不完就砍承諾，不准砍 test。承諾的品質必須當成第一優先。

D4: 我同意升 must-have。但要有防呆：locator 寫回去之前必須有驗證過的 evidence，連續失敗要能降級或隔離，而且這個 memory 只能改「怎麼找到元素」，不可以影響任務目標或安全政策。被污染的 memory 遠比沒有 memory 更糟

D5: 接受冷啟動，不要為這個花錢。但 UI 要講清楚現在在等什麼，另外首頁放幾個已經跑完的 run 可以直接點進去看，不要讓 grader 第一眼只看到轉圈，使用者體驗很差

D6: 走 stable flash + a11y tree / DOM。preview model 不用，理由跟你一樣，而且座標式操作沒辦法做確定性驗證，跟我們整個 verifier 的設計是反方向。座標策略放在 recovery 的 F4 當最後手段就好，找不到可靠元素就放棄，不要亂點

D7: 可以，但 primary document 跟 complete submission text 這兩份一定要真的抓下來並 hash，那是 Task 2 真正會吃的東西。其他 exhibits / XBRL / 圖檔只留 inventory metadata。如果 complete submission 超過你設的 cap，要明確標成沒抓到，嚴禁靜默截斷（靜默截斷正好就是我們在防的那種 silent failure）

其他你提的修正我都同意，特別是這幾條：
- H1 的定義加上純 client-side 的狀態改變。而且「必要」只能講成「case 宣告 + harness 驗證它確實發生」，README 就照這樣寫，不要寫成不可繞過
- 抄捷徑的反例 dev 也放一份
- H2 拆成 terminal_status + failure_class 兩個維度
- verified-wrong = 0 改成「在這幾份 eval 上、以第一次執行計算」，不是系統級保證。你講的「值對但取到隔壁欄 / 另一年度」那個缺口寫進 known limitation，label→value 的結構綁定要做
- exploration budget 跟 recovery reserve 分開算
- postcondition 在 plan 階段就 hash 凍結
- 每次 first run 記 git SHA + pinned model ID + eval set SHA
- validation 走你的 (a)。engineering 只拿得到總分跟 failure_class 分布，拿不到案例內容
- fixture 用獨立的公開 hostname，不要在 SSRF guard 上開例外洞
- fixture 加一頁 injection 測試
- SEC 自我限速 ≤1 rps
- secret 從架構上就不進 model context，regex gate 只當第二道

C3 你提醒得好。demo 跟 eval 用不同的 key，demo 端加 per-session run 上限，配額用完就顯示成一個設計過的狀態，不要讓它看起來像壞掉



接下來可以開始寫 frozen spec。另外有幾件事注意一下：
- dev set 進 repo。validation 跟 test 的案例內容不要進 repo，產出後直接貼給我，我自己存，repo 只留數量跟 hash
- seam 的介面另外寫一份短文件。我之後做 Task 2 會直接吃它，所以要能單獨看懂，不需要先讀完整份 spec
- 寫完之後自己再挑一輪，哪裡最可能被 acceptance reviewer 打就直接寫進文件當 known risk，不用另外再開一輪
- engineering session 跟 acceptance session 各自的驗收清單照你說的附上

==========
