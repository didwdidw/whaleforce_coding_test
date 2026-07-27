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

第一，維持 2 個真實站 must-have，Gutenberg 留 stretch。你的取捨理由我認同，locator memory 跟 safety suite 是評分重點，第三站不是。但 README 跟前端要把這件事寫成刻意的取捨，不要看起來像做不完。另外 "across different sites" 這條要求我認為不該靠站數回答，該靠 experimental tier——任意公開站都能試，試不出來就誠實棄權而且說明卡在哪。這才是我們拿去對這條需求的東西，spec 裡把這個連結講清楚

第二，fixture 不應該算進對外承諾。它是驗證工具，不是產品能力。拿自己出的考題當對外承諾，正好就是你 R-2 在擔心的事，而根本解法不是加緩解，是它本來就不該算
- 承諾只算真實站那幾條（Wikipedia 2 + toscrape 2）
- fixture 的 mutation / injection 全部走 gate suite
- 前端跟 README 都要明講 fixture 是我們自建的評測環境，不是支援的網站
- 這樣 test 的 8 格就有緩衝，你剛講的「每條承諾只能配 1 個案例」自己就解掉了。多出來的格子拿去放負向案例：查無結果、越界棄權、experimental 的未知站
- R-2 記得跟著更新

eval 現在就寫。dev 15 條進 repo。validation 跟 test 直接貼在回覆裡給我，不要寫成檔案，我怕不小心被 commit 進去。repo 只留數量跟 hash

寫的時候注意兩點：
1. test 的案例不要只是把 dev 換個同義詞。至少要換 entity、換頁型、換操作順序或換預期結果。要真的有測試的意義！
2. 你自己說的那條原則不變：如果某條承諾需要 2 個案例才站得住，就直接砍那條承諾，不要擠壓 test

==========

validation 跟 test 那幾條我認可了。寫成檔案放在 Users/tim/Desktops 底下好了

我們現在的 budget 只管 LLM call 次數，沒有管 token。但成本跟 free tier 配額是被 token 跟 request 數吃掉的，不是被 call 幾次吃掉的
比如說 S&P 500 那頁的 a11y tree 如果整棵送進去，一次 call 就可能塞好幾萬個 token

另外補一條 amendment：
- 每次 LLM call 要有 input token 上限。snapshot 進 model 之前一定要裁，只留互動元素、目標區塊、anchor 附近的文字，裁掉了什麼要留在 trace 裡（不然出錯時分不清是模型笨還是我們把證據裁掉了）
- 每個 run 記錄實際 input/output token 跟換算成本。A-25 說要 measured cost per run，但現在沒有任何東西會產生那個數字
- M0 除了讀限額，還要實測：拿 toscrape listing、S&P 500 條目、商品詳情頁各跑一次，回報單次 run 的 token 數跟美金成本

另外有件事我要在動工前知道：free tier 是按 requests per day 算的，一個 run 打 12 次就吃掉 12 個配額。dev 15 + validation 8 + test 8，跑一輪全套就是三四百個 request。一天的免費額度夠不夠跑完一輪？似乎完全不夠
M0 一併回報。不夠就直接講，我寧可花錢也不要卡進度（金額我再決定，你先給我數字就好）

然後 engineering session 的開場 brief 你寫吧
但寫短，並且要明確要求他是 enginnering session 要服從 spec，不可以自作主張。如果過程中有遇到窒礙難行的要求，或是實作過程中有發現更好的作法，可以停下來討論，但禁止自己決定。要求它自己會去讀 spec，你不用在 brief 裡把 spec 再講一遍。這裡要講的是它一開工就該知道、但不會自己從 spec 讀出來的東西：
1. 從哪開始、前兩個 milestone 的實際交付長怎樣
2. 有哪些坑。哪幾個地方最容易做出「看起來對但其實錯」的東西
3. 哪些事不准它自己決定，要回來問我

還有 validation 跟 test 的內容它永遠拿不到，只會拿到分數跟 failure_class 分布，這點在 brief 裡講明白，免得它之後跑來跟我要

==========

給 engineering agent 的 brief 我看過了，沒問題
engineering session 我會自己開，不用你操心，你不要開 sub-agent 去做
你這邊之後就是我需要改 spec 或有爭議或需要討論時再拉回來的 PM 角色

開工前先把以下錢的事寫進 brief 或是更新一下 spec

主機：
- 固定月費 10 美元以內，它自己挑
- 開發階段我建議先用 cloudflare tunnel 讓我的本地電腦當 host 就好。這個階段不該花時間糾結怎麼 host，應該著重功能性開發
- 但 M0 的 RAM 跟「從部署 IP 的可達性」還是要在真的雲端主機上量一次，不能用 tunnel 混過去。那條檢查存在的理由就是機房 IP 跟住宅 IP 會被差別對待，走我家網路會永遠是綠燈，然後在最後要部署的時候才發現站被擋。開個 container、curl 三個站、看一下記憶體就好，這是量測不是 hosting 決策
- 「花錢買掉 cold start」還是不准，這條不變

Gemini：
- 用量另外算。M0 如果顯示 free tier 塞不下一輪 eval，直接開 billing 去跑，累計 5 美元以內自己決定
- 我在 project folder 裡放了 api_keys。先把這個資料夾加進 .gitignore。Free_tier_agent_API_Key 是免費層，Billing_agent_API_Key 是付費層
- key 只准從檔案載入，不准印出內容、不准寫進任何 log、trace 或 prompt 記錄。S-2.13 本來就這樣要求，但現在 key 就躺在 repo 旁邊，很容易不小心 cat 出來然後進到要交出去的 prompts/ 裡
- free tier 打滿就 fallback 到付費，不用問我。但這只限 dev 跟 eval，公開 demo 那條路不准自動 fallback。理由是 S-11.11 把兩把 key 分開就是為了不讓外部流量吃掉評測配額，會自動跳過去的話那道牆等於沒有，而且「5 美元以內」是我的意圖，app 在 runtime 沒有東西能執行它
- trace 要記錄這次 run 用的是哪一把 key。A7.9 說免費層的內容 Google 會拿去改進產品、付費層不會，而 README 要揭露這件事，會靜默切換的話那個揭露就不準了
- 先做有限度的實驗看看每個 model 的效果，在效果可以接受的情況下使用成本最低的 model。https://ai.google.dev/gemini-api/docs/pricing 是唯一價格的 source of truth。

成本：
- 在 provider adapter 加一層 dev-only 的 response cache，prompt hash 命/ memory / mutation layer / UI 時重跑同一批 case 幾乎不用錢，改 prompt
才會 invalidate。這層只在 dev 模式開，validation 和 test 一律關掉，確保、成本數字是真的
- output token 也要有上限。A7 只鎖了 input，但 Gemini 把 thinking 算成 3 倍。打滿 budget 時 input 只佔 $0.018，thinking 一開自己就能吃掉 $0.06
- S-10.8 的「mutation gate suite 每次 build 都跑」改成有節制的觸發，這一項可能自己就佔掉三分之一的帳單
- Claude Code 的 sub-agent 用在 mutation seed、fixture 頁面、injection ce 批次分類、code review 這種離線工作，不進產品的 inference path。eval
案例還是我這邊出，它不要自己生

最後，M0 第一個 gate 大概就是第一個會爆的。這件事不用你解，但 brief 裡要讓它知道這是預期中的結果、不是它做錯了什麼。量出來不夠就換一個夠的，不要為了塞進去把 concurrency 或 budget 砍掉

M0 報告回來的時候，順便告訴我它挑了哪個 host 當最後正式使用的、為什麼，還有 cold start 大概多久

==========

ENG 在 M0 報告裡提了 Amendment 9 給我批。先讀 docs/m0-preflight-report.md，§9 是它的草稿，§5 和 §7 是依據

我批准了，但想修改一下，你來照我的旨意寫進 spec §16

- A9.1 / A9.3 / A9.4 照它的草稿收下。A9.3 那個「models.list() 會列出來、真的打才 404」是這份報告裡最有價值的一條
- A9.2 加一句：pin 定案前不准跑 validation 或 test。那兩份是 first-run 計分、綁 model ID 的，用暫定 model 去跑等於白燒一次 held-out run，而 held-out 的價值就在只能跑一次

哦再另外加三條：
- A9.5 — A8.11 的比較至少要放一個非 lite 的候選。一輪 $0.15，貴六倍也才 $0.9，在 $5 額度內，錢不是變數。pin 的依據是 locator reasoning 的品質，不是價格。also，報告表裡 3.6-flash 是 1.50/7.50、3.5-flash 是 1.50/9.00，同一價位帶挑 3.6
- A9.6 — 憑證政策延伸 A8.8：validation 和 test 一律走 billing API key，不管 free 還有沒有 quota。中途 quota 用盡是 blocked / provider_quota，而那輪不能重跑。另一個好處是 A7.9 的 README 揭露變乾淨，計分內容全部走付費層不會被拿去改進產品
- A9.7 — 服務要能無人值守連續運作兩週以上，這是驗收條件。三件事：瀏覽器 crash 之後自己起來、artifact store 和 log 的成長有上限不能塞爆磁碟、長時間累積的記憶體不能一路往上爬

A7.8 最後一行可以結案了。free tier 對 gemini-3.1-flash-lite 是 RPM 15 / TPM 250K / RPD 500。按 ENG 的 294 requests per round，500 / 294 = 一天只塞得下一輪，剩約兩百個 request 給開發迭代；跑到 S-6.1 的 12-call 上限（756/round）就不夠。所以 A9.6 那條不是偏好，是算出來的

報告 §7 有兩個已經不是 finding 而是需求變更，也一起處理：
- SEC 沒有 declared UA 直接 403。S-2.16 從 politeness 改成 functional precondition，seam 的測試要涵蓋 header 缺失
- Wikipedia 的 Crawl-delay: 5 在 SemrushBot 區塊底下，對我們不適用。README 不能把我們的 pacing 寫成 robots 義務，那是自願的

主機也定了，一起寫進去：
Tencent Cloud / Ashburn US，2 vCPU / 4 GB / 60 GB SSD，$4 per month，透過 Zeabur 租、Zeabur 當 deploy 層。在 S-11.9 的 $10 ceiling 內

寫完 commit，我再讓 engineering session 往下走

==========

Engineering agent 在 M1 抓到一個 robots 的實質違規，spec 要補

它原本用 urllib.robotparser。那個 parser 遇到空行就結束該群組，而 sec.gov/robots.txt 的 #SEC 區塊剛好在 User-agent: * 群組內的空行之後，所以 Disallow: /cgi-bin 和 Allow: /Archives/edgar/data 整段被丟掉

實測 cgi-bin/browse-edgar 是放行的
也就是系統會一邊爬 Disallowed 路徑、一邊相信自己合規。它另外還不支援 * 和 $，而且用第一條符合而非最長符合

S-2.3 現在只寫 enforce robots，這樣太鬆散了
語意要寫死：
- 依 RFC 9309
- 最長符合的規則勝出
- 同長度時 Allow 勝 Disallow
- 支援 * 萬用字元和 $ 結尾錨點
- 群組只在下一個 user-agent 行結束，空行不結束群組
- robots.txt 取不到時 fail closed

再加一條驗收要求：robots 的比對語意要有自己的單元測試，不能只靠 dev dataset
另外 engineering agent 有一句話值得一起寫進去: DEV-13 本來會矇對，因為那條規則剛好落在空行之前。這一類 bug 用 eval case 抓不到

順便處理第二個，也是實作跑在規格前面：
engineering agent 把 egress guard 做了三層防呆
1. APP_ENV 預設 production、沒設或拼錯都當 production，dev 是唯一能關掉 guard 的值
2. 誤設直接拒絕啟動
3. 每個 run 的 trace 第一步記錄 guard 狀態，被拒絕的 run 也記，同時掛在 /healthz

這些現在只在程式碼裡。要進 spec，理由是 reviewer 是黑箱對著 spec 檢查的。沒寫進去，他就沒有依據去驗這件事
engineering agent 那邊 32 個測試都過了，spec 這邊把要求補上就好

==========

M2 收了，gate 四項全過，87 個測試通過

engineering agent 提報一個決定要你裁量：
儲存是暫時的，這在 M2 從隱形變成問題：evidence bundle 是產品的核心主張，而它的 artifact 會在下次部署消失——打開才發現的懸空引用。修法是掛 volume，代價歸你：Zeabur 對掛了 volume 的服務會從 RollingUpdate 改成 Recreate，等於用上面量到的重疊 rollout 去換持久證據，每次部署要吃完整一輪開機的停機。

我感覺可以掛 volume。那個代價全部付在開發期，好處付在評分期，方向是對的。
寫成 Amendment 11。但不要只寫「掛個 volume」，有幾條是掛了 volume 也還在：
1. S-11.5 的首頁預跑 run 也會被保存期限吃掉。grader 兩週後打開，首頁三個示範 run 全是過期連結，而那是他看到的第一個畫面...
預跑 run 要嘛豁免於保存期限，要嘛到期自動重跑。你選一個寫進去。
2. 掛 volume 不解決過期。A9.7.2 說過期是記錄狀態不是刪除，但實際上 bytes 一定會被回收。所以 run detail 頁遇到不存在的 artifact，必須顯示成「已於某日過期」這種被記錄下來的狀態，不能是 404、不能是破圖。這條跟 volume 完全無關，本來就該有
3. /healthz 在 volume 沒掛上或不可寫的時候必須回不健康。不然它會靜靜退回暫時儲存，那正是我們現在要修的東西，而且從外面看不出來
4. 保存期限要真的被執行，上限綁磁碟——機器只有 60 GB，artifact 是截圖加 DOM。

順帶回報兩個 engineering agent 在寫 M2 測試時挖出來的舊 bug，都已修：沒有 claim 的 postcondition 會回報成功（「沒有失敗」被當成「全部通過」），以及 retention_days=0 因為 falsy 靜靜變成預設 14 天
第一個我想在 M3 之前往上收一層，等你這條回來一起給 engineering agent

==========

改動完 給我可以直接複製貼上給 engineering agent 的 prompt
簡述你改了什麼，spec哪裡有變，他下一步要做什麼

==========
