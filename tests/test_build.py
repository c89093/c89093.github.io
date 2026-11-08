"""Black-box contract tests for the static-site generator.

All site inputs and generated output live in a new TemporaryDirectory.  The
production-ready content below is invented for tests only; it does not approve
or publish the actual site's policies.
"""

import copy
import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
LOCALES = ("zh-hant", "en", "zh-hans")
ORIGIN = "https://c89093.github.io"
SLUG = "leveragedguard"
KINDS = ("home", "web", "app", "privacy", "terms")

spec = importlib.util.spec_from_file_location("site_build", REPO / "scripts" / "build.py")
if spec is None or spec.loader is None:
    raise ImportError("Cannot load scripts/build.py")
site_build = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = site_build
spec.loader.exec_module(site_build)


def url(locale, kind, slug=SLUG):
    suffix = {
        "home": "",
        "web": "privacy/",
        "app": f"{slug}/",
        "privacy": f"{slug}/privacy/",
        "terms": f"{slug}/terms/",
    }[kind]
    return f"/{locale}/{suffix}"


def html_path(page_url):
    return page_url.lstrip("/") + "index.html"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        self.text.append(data)

    def tags(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]

    def hrefs(self):
        return [a["href"] for a in self.tags("a") if "href" in a]


class BuildRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="site-regression-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(REPO / "site.json", self.root / "site.json")
        shutil.copytree(REPO / "content", self.root / "content")
        shutil.copytree(REPO / "assets", self.root / "assets")

    def config(self):
        return read_json(self.root / "site.json")

    def save_config(self, config):
        write_json(self.root / "site.json", config)

    def site_content(self, locale):
        return self.root / "content" / "site" / f"{locale}.json"

    def app_content(self, locale, slug=SLUG):
        return self.root / "content" / "apps" / slug / f"{locale}.json"

    def document(self, path):
        return Document((self.root / "dist" / path).read_text(encoding="utf-8"))

    def approve_fixture(self):
        config = self.config()
        config.update(operator_name="Fixture Publisher", contact_email="support@fixture-domain.org",
                      effective_date="2026-01-01", policies_approved=True)
        for app in config["apps"]:
            app["policies_approved"] = True
        self.save_config(config)
        for locale in LOCALES:
            path = self.site_content(locale)
            content = read_json(path)
            content.update(webIntro="Fixture website privacy notice.",
                           webSections=[["Fixture hosting", "Fixture hosting disclosure."]],
                           supportText="Contact the fixture publisher for support.")
            write_json(path, content)
            for app in config["apps"]:
                path = self.app_content(locale, app["slug"])
                content = read_json(path)
                content.update(policyIntro="Fixture app privacy notice.",
                               policy=[["Fixture data", "Fixture data handling disclosure."]],
                               termsIntro="Fixture terms notice.",
                               termsSections=[["Fixture terms", "Fixture terms details."]])
                write_json(path, content)

    def assert_no_deployable_output(self):
        dist = self.root / "dist"
        self.assertFalse(dist.exists() and any(dist.rglob("*.html")),
                         "A failed production build left deployable HTML in dist")

    def test_all_locales_page_kinds_manifest_and_page_url(self):
        manifest = site_build.build(self.root)
        self.assertEqual(manifest["mode"], "preview")
        expected = set()
        for locale in LOCALES:
            for kind in KINDS:
                slug = None if kind in ("home", "web") else SLUG
                page_url = url(locale, kind)
                with self.subTest(locale=locale, kind=kind):
                    self.assertEqual(site_build.page_url(locale, kind, slug), page_url)
                    path = html_path(page_url)
                    self.assertTrue((self.root / "dist" / path).is_file(), path)
                    expected.add((locale, kind, slug, path))
        actual = [(p["locale"], p["kind"], p["slug"], p["path"]) for p in manifest["pages"]]
        self.assertEqual(len(actual), len(expected), "Duplicate or missing page records")
        self.assertEqual(set(actual), expected)
        files = manifest["files"]
        self.assertEqual(len(files), len(set(files)))
        on_disk = {p.relative_to(self.root / "dist").as_posix()
                   for p in (self.root / "dist").rglob("*") if p.is_file()}
        self.assertEqual(set(files), on_disk)

    def test_language_switch_preserves_page_kind_and_app_slug(self):
        site_build.build(self.root)
        for locale in LOCALES:
            for kind in KINDS:
                with self.subTest(locale=locale, kind=kind):
                    doc = self.document(html_path(url(locale, kind)))
                    links = {urlparse(urljoin(ORIGIN + url(locale, kind), h)).path
                             for h in doc.hrefs()}
                    for target in LOCALES:
                        if target != locale:
                            self.assertIn(url(target, kind), links)

    def test_canonical_and_hreflang_on_every_page(self):
        site_build.build(self.root)
        for locale in LOCALES:
            for kind in KINDS:
                with self.subTest(locale=locale, kind=kind):
                    doc = self.document(html_path(url(locale, kind)))
                    links = doc.tags("link")
                    canonical = [a.get("href") for a in links
                                 if "canonical" in a.get("rel", "").lower().split()]
                    self.assertEqual(canonical, [ORIGIN + url(locale, kind)])
                    alternate = [a for a in links if "alternate" in a.get("rel", "").lower().split()
                                 and a.get("hreflang")]
                    mapped = {a["hreflang"].lower(): a.get("href") for a in alternate}
                    self.assertEqual(len(alternate), 4)
                    self.assertEqual(mapped, {**{loc: ORIGIN + url(loc, kind) for loc in LOCALES},
                                              "x-default": ORIGIN + url("zh-hant", kind)})

    def test_alias_404_robots_and_sitemap(self):
        self.approve_fixture()
        site_build.build(self.root, preview=False)
        dist = self.root / "dist"
        root_doc = self.document("index.html")
        targets = root_doc.hrefs() + [a.get("content", "") for a in root_doc.tags("meta")]
        self.assertTrue(any("/zh-hant/" in target for target in targets),
                        "Root alias must direct visitors to the default locale")
        not_found = self.document("404.html")
        self.assertTrue(not_found.hrefs(), "404 page needs a usable navigation link")
        robots = (dist / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(ORIGIN + "/sitemap.xml", robots)
        tree = ET.parse(dist / "sitemap.xml")
        locations = [el.text for el in tree.getroot().iter() if el.tag.rsplit("}", 1)[-1] == "loc"]
        expected = {ORIGIN + url(locale, kind) for locale in LOCALES for kind in KINDS}
        self.assertEqual(len(locations), len(expected))
        self.assertEqual(set(locations), expected)

    def test_html_content_is_escaped_not_executed(self):
        payload = 'Fixture <script>alert("x")</script> & <img src=x onerror=alert(1)>'
        path = self.site_content("en")
        content = read_json(path)
        content["intro"] = payload
        write_json(path, content)
        site_build.build(self.root)
        raw = (self.root / "dist" / "en" / "index.html").read_text(encoding="utf-8")
        doc = Document(raw)
        self.assertIn(payload, "".join(doc.text))
        self.assertNotIn('<script>alert("x")</script>', raw)
        self.assertFalse(any("onerror" in attrs for attrs in doc.tags("img")))
        self.assertIn("&lt;script&gt;", raw)
        self.assertIn("&amp;", raw)

    def test_second_app_generates_all_pages_without_template_changes(self):
        second = "fixture-app"
        config = self.config()
        app = copy.deepcopy(config["apps"][0])
        app["slug"] = second
        config["apps"].append(app)
        self.save_config(config)
        shutil.copytree(self.root / "content" / "apps" / SLUG,
                        self.root / "content" / "apps" / second)
        for locale in LOCALES:
            path = self.app_content(locale, second)
            content = read_json(path)
            content["name"] = "Fixture Second App"
            write_json(path, content)
        manifest = site_build.build(self.root)
        for locale in LOCALES:
            home = self.document(html_path(url(locale, "home")))
            self.assertIn(url(locale, "app", second), home.hrefs())
            self.assertIn("Fixture Second App", "".join(home.text))
            for kind in ("app", "privacy", "terms"):
                path = html_path(url(locale, kind, second))
                with self.subTest(locale=locale, kind=kind):
                    self.assertTrue((self.root / "dist" / path).is_file())
                    self.assertIn({"locale": locale, "kind": kind, "slug": second, "path": path},
                                  manifest["pages"])
                    doc = self.document(path)
                    links = {urlparse(urljoin(ORIGIN + url(locale, kind, second), h)).path
                             for h in doc.hrefs()}
                    for target in LOCALES:
                        if target != locale:
                            self.assertIn(url(target, kind, second), links)

    def test_approved_nondraft_word_depending_is_accepted(self):
        self.approve_fixture()
        path = self.site_content("en")
        content = read_json(path)
        content["supportText"] = "Support options vary depending on your request."
        write_json(path, content)
        self.assertEqual(site_build.build(self.root, preview=False)["mode"], "production")

    def test_approve_fixture_replaces_terms_draft_too(self):
        path = self.app_content("en")
        content = read_json(path)
        content["termsIntro"] = "Draft terms awaiting review."
        write_json(path, content)
        self.approve_fixture()
        self.assertEqual(site_build.build(self.root, preview=False)["mode"], "production")

    def test_vendor_privacy_links_are_present(self):
        site_build.build(self.root)
        for locale in LOCALES:
            website = self.document(html_path(url(locale, "web")))
            app = self.document(html_path(url(locale, "privacy")))
            self.assertIn("https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement", website.hrefs())
            self.assertIn("https://policies.google.com/privacy", website.hrefs())
            for provider in ("https://www.apple.com/legal/privacy/", "https://www.cloudflare.com/privacypolicy/", "https://policies.google.com/privacy"):
                self.assertIn(provider, app.hrefs())
            for doc in (website, app):
                self.assertIn("mailto:c89093@gmail.com", doc.hrefs())

    def test_missing_site_translation_is_rejected(self):
        self.site_content("zh-hans").unlink()
        with self.assertRaises(ValueError):
            site_build.build(self.root)

    def test_missing_app_translation_is_rejected(self):
        self.app_content("en").unlink()
        with self.assertRaises(ValueError):
            site_build.build(self.root)

    def test_missing_translation_key_is_rejected(self):
        path = self.app_content("en")
        content = read_json(path)
        del content["policyIntro"]
        write_json(path, content)
        with self.assertRaises(ValueError):
            site_build.build(self.root)

    def test_duplicate_slug_is_rejected(self):
        config = self.config()
        config["apps"].append(copy.deepcopy(config["apps"][0]))
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root)

    def test_illegal_slugs_are_rejected(self):
        original = self.config()
        for slug in ("", "../escape", "bad/name", "/absolute", "Bad Slug", "privacy"):
            with self.subTest(slug=slug):
                config = copy.deepcopy(original)
                config["apps"][0]["slug"] = slug
                self.save_config(config)
                with self.assertRaises(ValueError):
                    site_build.build(self.root)

    def test_testing_status_never_shows_a_download_link(self):
        config = self.config()
        config["apps"][0].update(status="testing", store_url="https://apps.apple.com/us/app/example/id123456789")
        self.save_config(config)
        site_build.build(self.root)
        for locale in LOCALES:
            for kind in ("home", "app"):
                with self.subTest(locale=locale, kind=kind):
                    doc = self.document(html_path(url(locale, kind)))
                    self.assertFalse(any("apps.apple.com" in href for href in doc.hrefs()))
                    self.assertNotIn(read_json(self.site_content(locale))["download"], "".join(doc.text))

    def test_released_app_shows_real_configured_store_link(self):
        config = self.config()
        store = "https://apps.apple.com/us/app/fixture/id123456789"
        config["apps"][0].update(status="released", store_url=store)
        self.save_config(config)
        site_build.build(self.root)
        for locale in LOCALES:
            with self.subTest(locale=locale):
                doc = self.document(html_path(url(locale, "app")))
                self.assertIn(store, doc.hrefs())
                self.assertIn(read_json(self.site_content(locale))["download"], "".join(doc.text))

    def test_testing_status_still_rejects_unsafe_store_urls(self):
        original = self.config()
        for store in ("javascript:alert(1)", "https://apps.apple.com.evil.example/id123",
                      "http://apps.apple.com/us/app/fixture/id123"):
            with self.subTest(store=store):
                config = copy.deepcopy(original)
                config["apps"][0].update(status="testing", store_url=store)
                self.save_config(config)
                with self.assertRaises(ValueError):
                    site_build.build(self.root)

    def test_public_contact_matches_owner_confirmation(self):
        config = self.config()
        self.assertEqual(config["display_name"], "Jam Chen")
        self.assertEqual(config["operator_name"], "Jam Chen")
        self.assertEqual(config["contact_email"], "c89093@gmail.com")
        site_build.build(self.root)
        for locale in LOCALES:
            for kind in ("home", "app"):
                with self.subTest(locale=locale, kind=kind):
                    doc = self.document(html_path(url(locale, kind)))
                    self.assertIn("Jam Chen", "".join(doc.text))
                    self.assertIn("mailto:c89093@gmail.com", doc.hrefs())

    def test_invalid_status_is_rejected(self):
        config = self.config()
        config["apps"][0]["status"] = "available"
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root)

    def test_invalid_released_store_urls_are_rejected(self):
        original = self.config()
        for store in (None, "", "http://apps.apple.com/us/app/example/id123",
                      "https://example.org/us/app/example/id123",
                      "https://apps.apple.com.evil.example/us/app/example/id123",
                      "https://apps.apple.com/us/app/example/idabc",
                      "https://apps.apple.com/us/app/example/id123/other"):
            with self.subTest(store=store):
                config = copy.deepcopy(original)
                config["apps"][0].update(status="released", store_url=store)
                self.save_config(config)
                with self.assertRaises(ValueError):
                    site_build.build(self.root)

    def test_production_requires_operator(self):
        self.approve_fixture()
        config = self.config()
        config["operator_name"] = None
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root, preview=False)
        self.assert_no_deployable_output()

    def test_production_requires_email(self):
        self.approve_fixture()
        config = self.config()
        config["contact_email"] = None
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root, preview=False)
        self.assert_no_deployable_output()

    def test_production_requires_effective_date(self):
        self.approve_fixture()
        config = self.config()
        config["effective_date"] = None
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root, preview=False)
        self.assert_no_deployable_output()

    def test_production_requires_site_policy_approval(self):
        self.approve_fixture()
        config = self.config()
        config["policies_approved"] = False
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root, preview=False)
        self.assert_no_deployable_output()

    def test_production_requires_each_app_policy_approval(self):
        self.approve_fixture()
        config = self.config()
        config["apps"][0]["policies_approved"] = False
        self.save_config(config)
        with self.assertRaises(ValueError):
            site_build.build(self.root, preview=False)
        self.assert_no_deployable_output()

    def test_production_rejects_review_copy_even_with_approval_flags(self):
        self.approve_fixture()
        path = self.app_content("zh-hant")
        content = read_json(path)
        # Keep the reviewed draft wording as a fixture. Later policy approval
        # must not turn this regression into a dependency on live draft text.
        content["policyIntro"] = "此頁是供負責人審閱的草稿，尚未生效。"
        write_json(path, content)
        with self.assertRaises(ValueError):
            site_build.build(self.root, preview=False)
        self.assert_no_deployable_output()

    def test_production_rejects_pending_content_in_policy_and_website(self):
        self.approve_fixture()
        cases = ((self.app_content("en"), "termsIntro", "Draft terms awaiting review."),
                 (self.app_content("en"), "termsSections", [["Terms", "Details pending confirmation."]]),
                 (self.app_content("en"), "policyIntro", "Draft policy awaiting review."),
                 (self.app_content("en"), "policy", [["Data", "Details pending confirmation."]]),
                 (self.site_content("en"), "webIntro", "Draft notice awaiting review."),
                 (self.site_content("en"), "webSections", [["Hosting", "Details pending confirmation."]]),
                 (self.site_content("en"), "supportText", "Contact details pending confirmation."))
        for path, key, value in cases:
            with self.subTest(key=key):
                original = read_json(path)
                changed = copy.deepcopy(original)
                changed[key] = value
                write_json(path, changed)
                try:
                    with self.assertRaises(ValueError):
                        site_build.build(self.root, preview=False)
                    self.assert_no_deployable_output()
                finally:
                    write_json(path, original)

    def test_preview_retains_draft_and_noindex(self):
        manifest = site_build.build(self.root, preview=True)
        self.assertEqual(manifest["mode"], "preview")
        for locale in LOCALES:
            site = read_json(self.site_content(locale))
            app = read_json(self.app_content(locale))
            policy = self.document(html_path(url(locale, "privacy")))
            self.assertIn(app["policyIntro"], "".join(policy.text))
            self.assertIn(site["draft"], "".join(policy.text))
            for kind in KINDS:
                with self.subTest(locale=locale, kind=kind):
                    doc = self.document(html_path(url(locale, kind)))
                    robots = [a.get("content", "").lower() for a in doc.tags("meta")
                              if a.get("name", "").lower() == "robots"]
                    self.assertTrue(any("noindex" in value for value in robots))

    def test_approved_isolated_fixture_builds_production(self):
        self.approve_fixture()
        manifest = site_build.build(self.root, preview=False)
        self.assertEqual(manifest["mode"], "production")
        for locale in LOCALES:
            for kind in KINDS:
                with self.subTest(locale=locale, kind=kind):
                    doc = self.document(html_path(url(locale, kind)))
                    robots = [a.get("content", "").lower() for a in doc.tags("meta")
                              if a.get("name", "").lower() == "robots"]
                    self.assertFalse(any("noindex" in value for value in robots))
            policy = self.document(html_path(url(locale, "privacy")))
            self.assertIn("Fixture app privacy notice.", "".join(policy.text))
        self.assertEqual(self.config()["contact_email"], "support@fixture-domain.org")

    def test_dist_excludes_sources_configuration_and_internal_evidence(self):
        self.approve_fixture()
        (self.root / "internal-evidence.txt").write_text("INTERNAL_EVIDENCE_SENTINEL", encoding="utf-8")
        (self.root / "credentials.txt").write_text("CREDENTIAL_SENTINEL", encoding="utf-8")
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "private-source.py").write_text("SOURCE_SENTINEL", encoding="utf-8")
        site_build.build(self.root, preview=False)
        dist = self.root / "dist"
        for file in dist.rglob("*"):
            if not file.is_file():
                continue
            relative = file.relative_to(dist)
            with self.subTest(path=relative.as_posix()):
                self.assertNotIn(relative.parts[0], ("content", "scripts", "tests", ".git"))
                self.assertNotIn(file.name, ("site.json", "internal-evidence.txt", "credentials.txt"))
                self.assertNotEqual(file.suffix, ".py")
                data = file.read_bytes()
                for sentinel in (b"INTERNAL_EVIDENCE_SENTINEL", b"CREDENTIAL_SENTINEL", b"SOURCE_SENTINEL"):
                    self.assertNotIn(sentinel, data)


if __name__ == "__main__":
    unittest.main()
