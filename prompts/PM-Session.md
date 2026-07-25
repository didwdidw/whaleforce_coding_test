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
