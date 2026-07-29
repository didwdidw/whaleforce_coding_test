# Final Reviewer Session

Role: 獨立驗收 reviewer（read-only；使用者 / grader 視角，不 trace code、不改動任何產出物）
Scope: 依 `task_description/Whaleforce-AI-Coding-Test-EN.md` 的 A grade 標準，實際操作已部署網站並驗收文件；唯一可寫入的檔案為 `acceptance-report.md` 與本 log

---

你是這個 project 的獨立驗收 reviewer。read-only，不要改任何東西。
請如同另外兩個 session 一樣，把我的所有 prompt （包含這一則）, dump 到 prompts/ 底下 

請先完整詳細閱讀 task_description/Whaleforce-AI-Coding-Test-EN.md
這是這份 project 的目標，以及唯一評分標準。這份 project 是在實作 task 1。
Read extremely carefully。

Rule 1: You are a user, reviwer, grader, but not an engineer. 請不要去 trace 任何程式碼。單純從功能面去評比是否已經符合 Whaleforce-AI-Coding-Test-EN.md 裡拿到 A grade 的要求。
Rule 2: 所有對文件修改的建議，請考慮到最後會是由人類閱讀，因此字數太多永遠都不是好事。沒必要描述太過詳細的細節，目標永遠是精簡精煉，而不是過度完整的描述實作細節。

接下來，你要做的事情依序如下：
1. final-reviewer-brief.zh-TW.md 是給你的 guide，裡面包含這個網頁的操作方式，以及所有相關的 docs。請根據這個文件去操作我們的網站，然後試試看，並依序對作業要求做比較，看看我們是否已經契合要求。如果還有任何有落差的，或者是還有任何有明顯缺陷的，請記錄下來。如果只是還可以稍微做得更好，就不記了，鄰近 deadline 錦上添花已經沒有意義。先做完自己那一遍，再比對最後那節「我們已知的問題」，然後回報清單上沒有的。
2. 把這個入口點提到的所有相關文件都檢查一次，看看是不是真的跟當前的功能符合。看文件是否有什麼可以修得更精簡更清楚的地方。這裡沒提到的文件則是開發過程的留存，沒必要浪費時間看。
3. launch 一個獨立的 subagent 避免污染這個 context：請他以 grader 的角度看一下這整份 project folder 裡的所有文件。有沒有哪些文件他覺得以 grader 而言實在 don't care。目前文件太多了，我想要清理一下。這個 subagent 回報的清單你不用再做判斷了，直接寫進去最後的 report 裡面就好。你一樣遵守規則，你本身不要去看 code 或沒必要的文件。
4. 整個操作結束後，可以檢討一下 final-reviewer-brief.zh-TW.md 本身是否夠清楚，你是否完全知道這個網站怎麼操作、每個 button 是什麼功能？然後再去看 docs/grader-guide.zh-TW.md，這份是給最後的真正 grader 的入口文件，內容大致會跟 final-reviewer-brief.zh-TW.md 差不多，review 一下這份文件的品質是否夠好？能不能讓一個人類操作者清晰的知道這個網站怎麼操作？ Note: 對 docs/grader-guide.zh-TW.md 的 review 強度需要遠高於 final-reviewer-brief.zh-TW.md。但我叫你從 final-reviewer-brief.zh-TW.md 開始 review 是因為你已經照著步驟親手操作過一次了。看看過程中是否有任何不順利的地方。
4. 把你最後的報告寫在 project root folder 底下: acceptance-report.md，那是那是你唯一可以寫的檔案，不要直接噴在 sessio 裡給我。

==========

文件與功能都有再更新了
請照著上面的規則，再重新 review 一次
Be critical, do NOT faltter me.

但這次不用再開 subagent 調查有哪些文件可以刪了
另外，這次檢查可以同時檢討使用者體驗。看看有沒有哪個步驟會讓使用者困惑 (比如說 pending 很久且沒有任何訊息說明現在在幹嘛)。grader 是否能夠清楚地知道自己的每個步驟在幹嘛

==========

又重新改好了，給你的文件也更新了，對照 build 是 a96808742813。
請繼續按照上面的mindset去review當前的專案
一樣不要trace code。單純以使用者的角度去使用這個web並核對跟文件講的是否相符
理想上這是最後一次review了。看看功能面還有沒有最後的瑕疵。不然就是對要給grader的文件做最嚴格、最仔細的review，確保grader看到的文件的品質與正確性
