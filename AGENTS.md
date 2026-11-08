# 開發者網站

保持靜態網站與最少依賴。內容在 content/，共用產生器在 scripts/build.py，資源在 assets/。

修改後執行 `python3 -m unittest discover -s tests -v` 與 `python3 scripts/build.py --preview`。公開發布必須使用 `--production`；不得跳過身分、客服信箱與政策核准檢查。不得代填私人帳號、捏造商店狀態或測試結果。

只發布 dist/，不將內部稽核、憑證、使用者資料或其他 App repository 內容加入此 repo。
