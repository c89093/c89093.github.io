"""Approved policy-copy regression: rights apply to data the operator can access."""
import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {'zh-hant': ['資料管理、聯絡與更新', '開發者無法存取你儲存在裝置及 iCloud 私人資料庫中的持倉、成本、現金、策略與歷史紀錄，因此無法代為查詢、提供副本、更正或刪除這些資料；相關保存與刪除限制請參閱前述說明。如對本政策或資料處理有疑問，可聯絡 Jam Chen（c89093@gmail.com）。你可就我們實際持有或可存取的個人資料（例如你主動寄送的支援信件），依適用法律提出查詢、提供副本、更正、停止處理或刪除等請求；我們會依實際資料範圍回覆，不會要求密碼，亦不影響你依法享有的權利。政策更新日期顯示於本頁，重大變更會在網站說明。'], 'en': ['Data management, contact, and updates', 'The developer cannot access your holdings, costs, cash, strategy, or history stored on your device or in your private iCloud database, and therefore cannot look up, provide copies of, correct, or delete those records on your behalf. See the retention and deletion limits above. For questions about this policy or data handling, contact Jam Chen at c89093@gmail.com. For personal data we actually hold or can access, such as support emails you choose to send us, you may request access, copies, correction, cessation of processing, deletion, or other rights under applicable law. We will respond within the scope of the data available to us and will not ask for passwords. This does not affect your legal rights. This page shows the policy update date; material changes will be explained on the website.'], 'zh-hans': ['数据管理、联系与更新', '开发者无法访问你保存在设备及 iCloud 私有数据库中的持仓、成本、现金、策略与历史记录，因此无法代为查询、提供副本、更正或删除这些数据；相关保留与删除限制请参阅前述说明。如对本政策或数据处理有疑问，可联系 Jam Chen（c89093@gmail.com）。你可就我们实际持有或可访问的个人数据（例如你主动发送的支持邮件），依适用法律提出查询、提供副本、更正、停止处理或删除等请求；我们会根据实际数据范围回复，不会要求密码，亦不影响你依法享有的权利。政策更新日期显示于本页，重大变更会在网站说明。']}

class Text(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(html)
    def handle_data(self, data):
        self.parts.append(data)

class PrivacyScopeTests(unittest.TestCase):
    def test_approved_copy_and_generated_pages(self):
        spec = importlib.util.spec_from_file_location('privacy_scope_build', ROOT / 'scripts/build.py')
        if spec is None or spec.loader is None:
            raise ImportError('Cannot load scripts/build.py')
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        with tempfile.TemporaryDirectory(prefix='privacy-scope-') as tmp:
            target = Path(tmp)
            shutil.copy2(ROOT / 'site.json', target / 'site.json')
            for folder in ('content', 'assets'):
                shutil.copytree(ROOT / folder, target / folder)
            build.build(target, preview=False)
            for locale, expected in EXPECTED.items():
                with self.subTest(locale=locale):
                    content = json.loads((target / 'content/apps/leveragedguard' / (locale + '.json')).read_text())
                    self.assertEqual(content['policy'][-1], expected)
                    html = (target / 'dist' / locale / 'leveragedguard/privacy/index.html').read_text()
                    text = ''.join(Text(html).parts)
                    for sentence in expected:
                        self.assertIn(sentence, text)
                    self.assertIn('Cloudflare Workers Logs', text)
                    self.assertIn('c89093@gmail.com', text)
                    if locale == 'zh-hant':
                        self.assertNotIn('必要身分', text)
                        self.assertNotIn('引導你透過 Apple 平台或支援處理', text)
                        self.assertNotIn('完全不蒐集', text)
            alias = (target / 'dist/leveragedguard/privacy/index.html').read_text()
            canonical = (target / 'dist/zh-hant/leveragedguard/privacy/index.html').read_text()
            self.assertEqual(alias, canonical)
