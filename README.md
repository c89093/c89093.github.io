# Jam Chen — 開發者網站

免後端、免 Python 第三方依賴的三語靜態網站。支援繁體中文、English、简体中文。網站三語不表示 App 已支援三語或已全球上架。

## 本機操作

需求：Python 3.10 以上。

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build.py --preview
python3 -m http.server 8080 --bind 127.0.0.1 --directory dist
```

瀏覽 `http://127.0.0.1:8080/`。伺服器以 Ctrl-C 停止；不要對外發布 preview。`dist/` 是可重建產物，不提交到 Git。

## 維護內容

- `site.json`：網站網址、公開署名／Email、政策日期／核准狀態、App 清單。
- `content/site/{locale}.json`：各語言首頁、共用導覽與網站隱私說明。
- `content/apps/{slug}/{locale}.json`：單一 App 的介紹、實際資料政策與使用風險說明。
- `assets/`：共用 CSS 與 App 品牌圖片；僅已登記圖片與 CSS 會進入產物。
- `scripts/build.py`：共用版型、驗證與輸出；沒有 CMS、JS runtime、追蹤或自動語言偵測。
- `tests/`：標準庫 unittest，fixture 與真實設定隔離。

新增 App：新增自己的 slug、圖片、完整三語內容，於 site.json 登記。不要複用其他 App 的資料政策。未上架用 `status: testing` 與 `store_url: null`；公開上架後才改成 `released` 並填入正確 Apple App Store URL。

URL 以 `/zh-hant/`、`/en/`、`/zh-hans/` 為語言前綴。各 App 為 `/{locale}/{slug}/`、`privacy/`、`terms/`。根與無語言前綴別名顯示繁中，canonical 指向繁中正式路由。未部署前這些只是預期路由，不是已上線網址。

## 正式發布

1. 檢查公開姓名與信箱是否正確、可收信；程式格式驗證不代表實際收信驗證。
2. 完成三語政策的實際資料流、保存／刪除限制、支援與權利處理資訊；核對日期並取得內容核准。不要只改 approval 旗標，草稿占位仍會被阻擋。
3. `site.json` 的網站與各 App `policies_approved` 設為 true，執行：

   ```sh
   python3 -m unittest discover -s tests -v
   python3 scripts/build.py --production
   ```

4. Repository 為 `c89093/c89093.github.io`。GitHub Settings → Pages → Source 選 **GitHub Actions**，並確認 `github-pages` environment 只允許核准來源部署。不要建立額外 deploy token。
5. 推送 main 後，檢查同一 commit 的 workflow 與 Pages deployment，逐頁以公開 HTTPS 查回。不能把 local build、成功 push 或檔案存在當成已上線。

Workflow 只上傳 `dist/`，不發布 source、site.json 或測試檔。Actions 使用已查證的官方 commit SHA；更新時須重新確認來源與測試。當 production gate 失敗時，不建立或上傳新的 deployment artifact；既有 local preview 不會因此被當成 production。

Apple 標準 EULA 使用官方連結，不自行複製／翻譯契約。網站政策不是法律審查結論；不可宣稱未實作的刪除功能、零平台日誌或保證報酬。

## 本機驗收界線

這個 repository 初始化與檔案建立不代表 GitHub repository 已建立。正式發布需另驗 GitHub 授權、遠端 commit、workflow 結果及公開頁面。App 設定連結只應接到已查回的公開頁面；本站工作不自動發布 TestFlight。
