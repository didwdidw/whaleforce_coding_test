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
