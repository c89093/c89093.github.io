#!/usr/bin/env python3
"""Build the developer website using only the Python standard library."""
import argparse
from datetime import date
from html import escape
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit, quote
from xml.sax.saxutils import escape as xml_escape

LANGUAGES = {'zh-hant': ('zh-Hant', '繁體中文'), 'en': ('en', 'English'), 'zh-hans': ('zh-Hans', '简体中文')}
EULA = 'https://www.apple.com/legal/internet-services/itunes/dev/stdeula/'
GITHUB_PRIVACY = 'https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement'
GENERATOR = 'jam-static-site-v1'
UI_FIELDS = set('preview draft role apps support back hero intro browse collection collectionDesc privacy terms sitePrivacy eula supportText contactPending supportHint webIntro webSections providerPolicy contents updated publisher emailLabel download notFound notFoundText skip released'.split())
APP_FIELDS = set('status platform tag name appDesc learn appHero appIntro release featuresTitle features policyIntro policy termsIntro termsSections'.split())
SECTION_FIELDS = {'features', 'policy', 'termsSections', 'webSections'}
ARRAY_FIELDS = {'hero', 'appHero'}
RESERVED = {'assets', 'privacy', 'en', 'zh-hant', 'zh-hans', '404', 'dist', 'content', 'scripts', 'tests'}
DRAFT_PATTERNS = ('草稿', '待確認', '待确认', '待負責人', '待负责人', '尚未生效', 'draft', 'pending', 'awaiting', 'will specify', '正式政策需', '正式政策中列明', 'final policy must')


def text(value):
    return escape(str(value), quote=True)


def page_url(locale, kind, slug=None):
    if locale not in LANGUAGES:
        raise ValueError('Unknown locale')
    if kind == 'home':
        return f'/{locale}/'
    if kind == 'web':
        return f'/{locale}/privacy/'
    if kind not in ('app', 'privacy', 'terms') or not slug:
        raise ValueError('Invalid page kind or app slug')
    return f'/{locale}/{slug}/' + ('' if kind == 'app' else kind + '/')


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(f'Cannot read valid JSON: {path.name}') from error


def check_content(data, required, label):
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError(f'{label}: translation keys differ from the content contract')
    for key, value in data.items():
        if key in SECTION_FIELDS:
            valid = isinstance(value, list) and len(value) > 0 and all(
                isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, str) and v.strip() for v in pair)
                for pair in value)
        elif key in ARRAY_FIELDS:
            valid = isinstance(value, list) and bool(value) and all(isinstance(v, str) and v.strip() for v in value)
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise ValueError(f'{label}: invalid content field {key}')


def https_url(value, label, host=None, origin=False):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{label}: HTTPS URL required')
    try:
        p = urlsplit(value)
        valid = p.scheme == 'https' and p.hostname and not p.username and not p.password and not p.fragment
        valid = valid and (not host or p.hostname == host)
        if origin:
            valid = valid and p.path in ('', '/') and not p.query and p.port is None
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f'{label}: invalid HTTPS URL')
    return value.rstrip('/') if origin else value


def load(root, preview):
    config = read_json(root / 'site.json')
    config['origin'] = https_url(config.get('origin'), 'origin', origin=True)
    https_url(config.get('github_url'), 'github_url', host='github.com')
    if not isinstance(config.get('display_name'), str) or not config['display_name'].strip():
        raise ValueError('display_name is required')
    ui = {}
    for locale in LANGUAGES:
        ui[locale] = read_json(root / 'content/site' / (locale + '.json'))
        check_content(ui[locale], UI_FIELDS, 'site/' + locale)
    entries = config.get('apps')
    if not isinstance(entries, list) or not entries:
        raise ValueError('At least one app is required')
    apps, seen = [], set()
    for metadata in entries:
        slug = metadata.get('slug', '')
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', slug) or slug in RESERVED or slug in seen:
            raise ValueError('Invalid, reserved or duplicate app slug')
        seen.add(slug)
        icon = metadata.get('icon', '')
        if not isinstance(icon, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+\.(png|jpg|webp|svg)', icon):
            raise ValueError(f'{slug}: invalid icon filename')
        asset = root / 'assets' / icon
        if not asset.is_file() or asset.is_symlink():
            raise ValueError(f'{slug}: missing or unsafe icon asset')
        if metadata.get('status') not in ('testing', 'released'):
            raise ValueError(f'{slug}: invalid release status')
        store = metadata.get('store_url')
        if store is not None:
            https_url(store, slug + ' store_url', host='apps.apple.com')
            if not re.search(r'/id\d+/?$', urlsplit(store).path):
                raise ValueError(f'{slug}: App Store URL must identify an app')
        if metadata['status'] == 'released' and not store:
            raise ValueError(f'{slug}: released apps require store_url')
        localized = {}
        for locale in LANGUAGES:
            localized[locale] = read_json(root / 'content/apps' / slug / (locale + '.json'))
            check_content(localized[locale], APP_FIELDS, slug + '/' + locale)
        apps.append(dict(metadata, localized=localized))
    if not preview:
        missing = []
        if not isinstance(config.get('operator_name'), str) or not config['operator_name'].strip():
            missing.append('operator_name')
        email = config.get('contact_email')
        if not isinstance(email, str) or not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}', email):
            missing.append('contact_email')
        elif email.rsplit('@', 1)[1].lower() in {'example.com', 'example.org', 'example.net'} or email.endswith(('.invalid', '.test', '.localhost')):
            missing.append('contact_email must not be a placeholder')
        try:
            value = config.get('effective_date')
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError('Invalid date')
            if date.fromisoformat(value) > date.today():
                raise ValueError('Future date')
        except (ValueError, TypeError):
            missing.append('effective_date')
        if config.get('policies_approved') is not True:
            missing.append('website policy approval')
        for app in apps:
            if app.get('policies_approved') is not True:
                missing.append(app['slug'] + ' policy approval')
        if missing:
            raise ValueError('Production blocked: ' + ', '.join(missing))
        for locale in LANGUAGES:
            actual = [ui[locale]['webIntro'], ui[locale]['webSections'], ui[locale]['supportText']]
            for app in apps:
                d = app['localized'][locale]
                actual.extend([d['policyIntro'], d['policy'], d['termsIntro'], d['termsSections']])
            flat = json.dumps(actual, ensure_ascii=False).casefold()
            if any(re.search(r'\b' + re.escape(term.casefold()) + r'\b', flat) if term.isascii() else term in flat for term in DRAFT_PATTERNS):
                raise ValueError('Production blocked: unfinished policy text in ' + locale)
    return config, ui, apps


def link(href, label, cls=''):
    return f'<a href="{text(href)}" class="{text(cls)}">{text(label)}</a>'


def art(app, name):
    return f'<div class="app-art"><img src="/assets/{text(app["icon"])}" width="256" height="256" alt="{text(name)}"></div>'


def support(ui, config):
    email = config.get('contact_email')
    contact = link('mailto:' + quote(email, safe='@.'), email, 'text-link') if email else f'<span class="pending">{text(ui["contactPending"])}</span>'
    return f'<section class="support" id="support"><h2>{text(ui["support"])}</h2><div><p>{text(ui["supportText"])}</p><div class="links">{contact}</div><small>{text(ui["supportHint"])}</small></div></section>'


def card(locale, ui, app):
    d, slug = app['localized'][locale], app['slug']
    status = ui['released'] if app['status'] == 'released' else d['status']
    return f'<div class="app-card">{art(app,d["name"])}<div class="app-copy"><span class="badge">{text(status)}</span><h3>{text(d["name"])}</h3><p>{text(d["appDesc"])}</p><div class="links">{link(page_url(locale,"app",slug),d["learn"]+" ↗","button")}{link(page_url(locale,"privacy",slug),ui["privacy"],"text-link")}</div><div class="platform">{text(d["platform"])}</div></div></div>'


def render(locale, kind, config, all_ui, apps, preview, app=None):
    ui = all_ui[locale]
    slug = app['slug'] if app else None
    d = app['localized'][locale] if app else None
    brand = config['display_name']
    nav = ''.join(f'<a href="{page_url(loc,kind,slug)}" lang="{LANGUAGES[loc][0]}" hreflang="{LANGUAGES[loc][0]}"'+(' aria-current="page"' if loc == locale else '')+f'>{LANGUAGES[loc][1]}</a>' for loc in LANGUAGES)
    badge = f'<div class="preview">{text(ui["preview"])}</div>' if preview else ''
    header = f'{link("#main",ui["skip"],"skip-link")}{badge}<header><div class="wrap nav"><a class="brand" href="{page_url(locale,"home")}"><span class="monogram" aria-hidden="true">{text(brand[0])}</span>{text(brand)}</a><div class="nav-right">{link(page_url(locale,"home")+"#apps",ui["apps"])}{link(page_url(locale,"home")+"#support",ui["support"])}<nav class="languages" aria-label="Language">{nav}</nav></div></div></header>'
    if kind == 'home':
        title, description = brand + ' — ' + ui['role'], ui['intro']
        body = f'<section class="hero"><div class="eyebrow">{text(ui["role"])}</div><h1>'+''.join(f'<span>{text(s)}</span>' for s in ui['hero'])+f'</h1><p class="lead">{text(ui["intro"])}</p>{link("#apps",ui["browse"]+" ↓","button")}</section>'
        body += f'<section id="apps"><div class="section-heading"><h2>{text(ui["collection"])}</h2><p>{text(ui["collectionDesc"])}</p></div>'+''.join(card(locale,ui,a) for a in apps)+'</section>'+support(ui,config)
    elif kind == 'app':
        if app is None or d is None:
            raise ValueError('App page requires app content')
        title, description = d['name'] + ' — ' + brand, d['appDesc']
        status = ui['released'] if app['status'] == 'released' else d['status']
        release = link(app['store_url'],ui['download'],'button') if app['status'] == 'released' else f'<p class="release">{text(d["release"])}</p>'
        body = link(page_url(locale,'home'),'← '+ui['back'],'back')+f'<section class="product-hero"><div><div class="eyebrow">{text(d["name"])} / {text(d["tag"])}</div><h1>'+''.join(f'<span>{text(s)}</span>' for s in d['appHero'])+f'</h1><p class="lead">{text(d["appIntro"])}</p><div class="links"><span class="badge">{text(status)}</span><span class="platform">{text(d["platform"])}</span></div>{release}</div>{art(app,d["name"])}</section>'
        body += f'<section><h2>{text(d["featuresTitle"])}</h2><div class="feature-grid">'+''.join(f'<div class="feature"><span class="feature-mark" aria-hidden="true">{["◒","▤","↔"][i%3]}</span><h3>{text(t)}</h3><p>{text(p)}</p></div>' for i,(t,p) in enumerate(d['features']))+'</div></section>'
        body += f'<div class="web-note"><div class="links">{link(page_url(locale,"privacy",slug),ui["privacy"])}{link(page_url(locale,"terms",slug),ui["terms"])}{link(EULA,ui["eula"]+" ↗")}</div></div>'+support(ui,config)
    else:
        if kind != 'web' and (d is None or app is None):
            raise ValueError('App policy requires app content')
        d = d or {}
        label = ui[{'privacy':'privacy','terms':'terms','web':'sitePrivacy'}[kind]]
        intro = ui['webIntro'] if kind == 'web' else d[{'privacy':'policyIntro','terms':'termsIntro'}[kind]]
        sections = ui['webSections'] if kind == 'web' else d[{'privacy':'policy','terms':'termsSections'}[kind]]
        title, description = ((d['name']+' — ') if d else '')+label, intro
        back_kind, back_name = ('home',brand) if kind == 'web' else ('app',d['name'])
        toc = ''.join(link(f'#section-{i}',t) for i,(t,_) in enumerate(sections))
        content = ''.join(f'<section id="section-{i}"><h2>{text(t)}</h2><p>{text(p)}</p></section>' for i,(t,p) in enumerate(sections))
        if kind == 'web':
            extra = link(GITHUB_PRIVACY, ui['providerPolicy']) + link('https://policies.google.com/privacy', 'Google · '+ui['privacy'])
        elif kind == 'privacy':
            providers = [('Apple', 'https://www.apple.com/legal/privacy/'), ('Cloudflare', 'https://www.cloudflare.com/privacypolicy/'), ('Google', 'https://policies.google.com/privacy')]
            extra = ''.join(link(href, name+' · '+ui['privacy']) for name,href in providers)
            extra += link('https://developers.cloudflare.com/workers/observability/logs/workers-logs/', 'Cloudflare Workers Logs')
        else:
            extra = link(EULA, ui['eula']+' ↗')
        if config.get('contact_email'):
            extra += link('mailto:'+quote(config['contact_email'], safe='@.'), config['contact_email'])
        notice = f'<div class="draft">{text(ui["draft"])}</div>' if preview else ''
        metadata = ''
        if config.get('effective_date'):
            metadata += f'<p class="meta">{text(ui["updated"])}: {text(config["effective_date"])}</p>'
        if config.get('operator_name'):
            metadata += f'<p class="meta">{text(ui["publisher"])}: {text(config["operator_name"])}</p>'
        body = link(page_url(locale,back_kind,slug),'← '+back_name,'back')+f'<div class="document-layout"><nav class="toc" aria-label="{text(ui["contents"])}"><strong>{text(ui["contents"])}</strong>{toc}</nav><article><div class="eyebrow">{text(d["name"] if d else brand)}</div><h1>{text(label)}</h1><p class="lead">{text(intro)}</p>{metadata}{notice}{content}<div class="legal-links">{extra}{link(page_url(locale,"home")+"#support",ui["support"])}</div></article></div>'
    footer = f'<footer><div class="wrap footer-inner"><span>{text(brand)} · {text(ui["role"])}</span><div class="footer-links">{link(page_url(locale,"web"),ui["sitePrivacy"])}{link(config["github_url"],"GitHub ↗")}{link(EULA,ui["eula"])}</div></div></footer>'
    canonical = config['origin']+page_url(locale,kind,slug)
    alternates = ''.join(f'<link rel="alternate" hreflang="{LANGUAGES[loc][0]}" href="{text(config["origin"]+page_url(loc,kind,slug))}">' for loc in LANGUAGES)
    alternates += f'<link rel="alternate" hreflang="x-default" href="{text(config["origin"]+page_url("zh-hant",kind,slug))}">'
    robots = 'noindex,nofollow' if preview else 'index,follow'
    return f'<!doctype html><html lang="{LANGUAGES[locale][0]}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="{robots}"><meta name="description" content="{text(description)}"><meta name="referrer" content="strict-origin-when-cross-origin"><title>{text(title)}</title><link rel="canonical" href="{text(canonical)}">{alternates}<link rel="stylesheet" href="/assets/site.css"><link rel="icon" href="/assets/{text(apps[0]["icon"])}"></head><body>{header}<main class="wrap" id="main">{body}</main>{footer}</body></html>'


def build(root, preview=True):
    root = Path(root).resolve()
    # Validate before touching existing output. A failed production request must not
    # relabel or mutate an earlier preview into a deployment artifact.
    config, ui, apps = load(root, preview)
    out = root / 'dist'
    if out.is_symlink():
        raise ValueError('Refusing symlink output directory')
    if out.exists():
        marker = out / '.site-build.json'
        if not marker.is_file() or read_json(marker).get('generator') != GENERATOR:
            raise ValueError('Refusing to replace an unowned output directory')
        shutil.rmtree(out)
    out.mkdir()
    pages, files = [], []
    def emit(path, content):
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        files.append(path)
    for locale in LANGUAGES:
        for kind, app in [('home',None),('web',None)] + [(k,a) for a in apps for k in ('app','privacy','terms')]:
            slug = app['slug'] if app else None
            path = page_url(locale,kind,slug).lstrip('/')+'index.html'
            emit(path,render(locale,kind,config,ui,apps,preview,app))
            pages.append({'locale':locale,'kind':kind,'slug':slug,'path':path})
    for entry in [e for e in pages if e['locale']=='zh-hant']:
        alias = entry['path'].removeprefix('zh-hant/')
        emit(alias,(out/entry['path']).read_text(encoding='utf-8'))
    # Only explicitly selected assets enter the deployable directory.
    for asset in ['site.css'] + sorted({a['icon'] for a in apps}):
        source = root/'assets'/asset
        if not source.is_file() or source.is_symlink():
            raise ValueError('Missing or unsafe asset: '+asset)
        (out/'assets').mkdir(exist_ok=True)
        shutil.copyfile(source,out/'assets'/asset)
        files.append('assets/'+asset)
    error_sections = ''.join(f'<section lang="{LANGUAGES[loc][0]}"><h2>{text(ui[loc]["notFound"])}</h2><p>{text(ui[loc]["notFoundText"])}</p>{link(page_url(loc,"home"),LANGUAGES[loc][1])}</section>' for loc in LANGUAGES)
    emit('404.html',f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>404 — {text(config["display_name"])}</title><link rel="stylesheet" href="/assets/site.css"></head><body><main class="wrap not-found"><h1>404</h1>{error_sections}</main></body></html>')
    urls = ''.join('<url><loc>'+xml_escape(config['origin']+'/'+p['path'].removesuffix('index.html'))+'</loc></url>' for p in pages)
    emit('sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+urls+'</urlset>')
    emit('robots.txt','User-agent: *\nDisallow: /\n' if preview else 'User-agent: *\nAllow: /\nSitemap: '+config['origin']+'/sitemap.xml\n')
    emit('.nojekyll','')
    manifest = {'generator':GENERATOR,'mode':'preview' if preview else 'production','pages':pages,'files':sorted(files+['.site-build.json'])}
    emit('.site-build.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview',action='store_true')
    mode.add_argument('--production',action='store_true')
    args = parser.parse_args()
    try:
        manifest = build(Path(__file__).resolve().parents[1],preview=args.preview)
    except ValueError as error:
        print(str(error),file=sys.stderr)
        return 1
    print(json.dumps({'mode':manifest['mode'],'localized_pages':len(manifest['pages']),'output':'dist/'},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
